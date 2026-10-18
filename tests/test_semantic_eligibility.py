"""Eligibility regressions with real hybrid scoring and no model downloads."""
import unittest
from dataclasses import replace
from unittest.mock import MagicMock, patch

from core.corpus import build_corpus
from core.engine import HocVuEngine
from core.scenarios import expand_retrieval_query
from core.searcher import HybridSearcher
from core.settings import AppConfig, MODELS
from core.splitter import split_regulation


class SemanticEligibilityTests(unittest.TestCase):
    ref_date = "2026-10-05"
    scholarship = ("QD-HBHT-HPU-2026", "Điều 1", ("1",))
    language = ("QD-DTDC-HPU-2026", "Điều 2", ("1",))
    payment = ("QD-HBHT-HPU-2026", "Điều 5", ("1",))
    funding = ("QD-HBHT-HPU-2026", "Điều 1", ("2",))

    @classmethod
    def setUpClass(cls):
        cls.chunks = [
            chunk for regulation in build_corpus()
            for chunk in split_regulation(regulation, 800, 1)
        ]

    @staticmethod
    def identity(chunk):
        return chunk.rid, chunk.aid, tuple(chunk.clause_ids)

    def make_searcher(self, favored, distractor):
        config = AppConfig(max_units=2, semantic_enabled=True)
        # Patch the constructor where HybridSearcher imports it, before build:
        # neither SentenceTransformer nor its weights can be loaded.
        with patch("core.searcher.SemanticEncoder") as encoder_type:
            encoder = encoder_type.return_value
            encoder.available = True
            encoder.build.return_value = True
            scores = [
                0.99 if self.identity(chunk) == distractor else
                0.60 if self.identity(chunk) == favored else -0.20
                for chunk in self.chunks
            ]
            self.assertEqual(scores.count(0.99), 1)
            self.assertEqual(scores.count(0.60), 1)
            encoder.similarities.return_value = scores
            searcher = HybridSearcher(config)
            searcher.build(self.chunks)
            encoder_type.assert_called_once_with(config.embedding_model, MODELS)
            encoder.build.assert_called_once_with([
                f"{chunk.art_heading}\n{chunk.text}" for chunk in self.chunks
            ])
        self.assertEqual(searcher.provider, "bm25+multilingual-e5")
        self.assertEqual(searcher.semantic_error, "")
        return searcher, encoder

    def assert_blended_search(self, searcher, encoder, question, distractor):
        hits = searcher.search(question, len(self.chunks), self.ref_date)
        encoder.similarities.assert_called_once_with(question)
        encoder.similarities.reset_mock()
        self.assertEqual(self.identity(hits[0].chunk), distractor)
        peak = max(hit.bm25 for hit in hits)
        for hit in hits:
            self.assertAlmostEqual(
                hit.score,
                searcher.config.bm25_weight * hit.bm25 / peak
                + (1 - searcher.config.bm25_weight) * max(0, hit.vec),
            )
        self.assertTrue(any(hit.vec < 0 for hit in hits))
        return hits

    def ask(self, searcher, encoder, question):
        with patch("core.engine.SessionStore", return_value=MagicMock()):
            engine = HocVuEngine(searcher.config, searcher)
        response = engine.ask(
            question, "semantic-eligibility", use_context=False,
            record_session=False, ref_date=self.ref_date,
        )
        encoder.similarities.assert_called_once_with(expand_retrieval_query(question))
        encoder.similarities.reset_mock()
        engine.session.add_turn.assert_not_called()
        self.assertEqual(response.providers["retrieval"], "bm25+multilingual-e5")
        return response

    def test_scholarship_eligibility_beats_high_similarity_distractors(self):
        for distractor in (self.language, self.payment, self.funding):
            for question in ("Điều kiện nhận học bổng", "dieu kien nhan hoc bong"):
                with self.subTest(question=question, distractor=distractor):
                    searcher, encoder = self.make_searcher(self.scholarship, distractor)
                    hits = self.assert_blended_search(searcher, encoder, question, distractor)
                    reranked = searcher.rerank_by_coverage(question, hits)
                    self.assertEqual(self.identity(reranked[0].chunk), self.scholarship)
                    response = self.ask(searcher, encoder, question)
                    self.assertFalse(response.refused)
                    reference = response.references[0]
                    self.assertEqual(self.identity(reference), self.scholarship)
                    self.assertIn("kết quả học tập và điểm rèn luyện", reference.excerpt)
                    self.assertIn("kết quả học tập và điểm rèn luyện", response.answer)
                    self.assertNotIn("TOEIC", response.answer)
                    self.assertNotIn("chuyển khoản", response.answer)

    def test_equivalent_conditions_queries_keep_other_topics_grounded(self):
        cases = (
            (
                ("Điều kiện bảo lưu kết quả học tập", "dieu kien bao luu ket qua hoc tap"),
                ("QD-DTDC-HPU-2026", "Điều 5", ("2",)), "ít nhất 1 học kỳ",
            ),
            (
                ("Điều kiện để học song ngành là gì?", "dieu kien de hoc song nganh la gi"),
                ("QD-DTDC-HPU-2026", "Điều 6", ("1",)), "2.8",
            ),
            (
                ("Điều kiện đi thực tập", "dieu kien di thuc tap"),
                ("QD-TTTN-HPU-2026", "Điều 1", ("1",)), "110 tín chỉ",
            ),
        )
        for questions, expected, excerpt in cases:
            for question in questions:
                with self.subTest(question=question):
                    searcher, encoder = self.make_searcher(expected, self.language)
                    hits = self.assert_blended_search(searcher, encoder, question, self.language)
                    self.assertEqual(
                        self.identity(searcher.rerank_by_coverage(question, hits)[0].chunk),
                        expected,
                    )
                    response = self.ask(searcher, encoder, question)
                    self.assertFalse(response.refused)
                    self.assertEqual(self.identity(response.references[0]), expected)
                    self.assertIn(excerpt, response.answer)

    def test_high_semantic_confidence_does_not_override_refusal(self):
        for question in (
            "Điều kiện nhận học bổng bóng đá là gì?",
            "Trường có tổ chức giải bóng đá sinh viên không?",
            "truong co to chuc giai bong da sinh vien khong",
        ):
            with self.subTest(question=question):
                searcher, encoder = self.make_searcher(self.language, self.scholarship)
                self.assert_blended_search(searcher, encoder, question, self.scholarship)
                response = self.ask(searcher, encoder, question)
                self.assertTrue(response.retrieved)
                self.assertGreaterEqual(response.confidence, searcher.config.semantic_floor)
                self.assertFalse(searcher.has_specific_evidence(question, response.retrieved))
                self.assertTrue(response.refused)
                self.assertFalse(response.references)
                self.assertEqual(response.refusal_reason, "Insufficient grounded context")
                # The refusal outcome and reason must match lexical-only search.
                lexical = HybridSearcher(replace(searcher.config, semantic_enabled=False))
                lexical.build(self.chunks)
                with patch("core.engine.SessionStore", return_value=MagicMock()):
                    baseline = HocVuEngine(lexical.config, lexical).ask(
                        question, "lexical-baseline", use_context=False,
                        record_session=False, ref_date=self.ref_date,
                    )
                self.assertEqual(response.refused, baseline.refused)
                self.assertEqual(response.references, baseline.references)
                self.assertEqual(response.refusal_reason, baseline.refusal_reason)


if __name__ == "__main__":
    unittest.main()
