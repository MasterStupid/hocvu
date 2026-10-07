import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.classifier import Classifier, Intent
from core.corpus import build_corpus
from core.generator import Generator
from core.searcher import HybridSearcher
from core.scenarios import expand_retrieval_query, is_attendance_training_scenario
from core.settings import AppConfig
from core.engine import HocVuEngine
from core.models import Response
from core.nlp import content_tokens
from core.splitter import split_regulation


class RagPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = AppConfig(max_units=2, semantic_enabled=False)
        chunks = [chunk for regulation in build_corpus() for chunk in split_regulation(regulation, 800, 1)]
        cls.searcher = HybridSearcher(cls.config)
        cls.searcher.build(chunks)

    def test_retrieves_a_grounded_bao_luu_clause(self):
        hits = self.searcher.search("Điều kiện bảo lưu kết quả học tập", 3, "2026-10-04")
        self.assertTrue(hits)
        self.assertEqual(hits[0].chunk.aid, "Điều 5")
        self.assertIn("Bảo lưu", hits[0].chunk.art_heading)

    def test_filters_expired_regulations_for_current_query(self):
        hits = self.searcher.search("Quy định cũ có cho phép thi lại không", 10, "2026-10-04")
        self.assertTrue(all(hit.chunk.valid_until != "2026-08-31" for hit in hits))

    def test_lets_unknown_topic_reach_retrieval_then_refuses_without_evidence(self):
        # Scope is determined by evidence, not a closed keyword allowlist.
        self.assertEqual(Classifier().classify("Căng tin trường có món gì?"), Intent.ACADEMIC_RULES)
        engine = HocVuEngine(self.config, self.searcher)
        for question in ("Căng tin trường có món gì?", "Xe bus tuyến nào đi ngang qua cổng chính của Đại học Hải Phòng?", "Trường có tổ chức giải bóng đá sinh viên không?"):
            with self.subTest(question=question):
                response = engine.ask(question, "out-of-scope", use_context=False, record_session=False)
                self.assertTrue(response.refused)

    def test_does_not_treat_thi_lai_as_a_greeting(self):
        classifier = Classifier()
        self.assertEqual(classifier.classify("thi lại"), Intent.ACADEMIC_RULES)
        self.assertEqual(classifier.classify("Khi nào thi học kỳ?"), Intent.ACADEMIC_RULES)

    def test_admits_administrative_document_question_but_blocks_casual_question(self):
        classifier = Classifier()
        self.assertEqual(classifier.classify("Tại sao một con vịt lại sinh ra một con gà?"), Intent.ACADEMIC_RULES)
        self.assertEqual(classifier.classify("Thời hạn cung cấp thông tin là khi nào?"), Intent.ACADEMIC_RULES)

    def test_stopwords_keep_academic_words_that_collide_after_accent_stripping(self):
        terms = content_tokens("Điểm rèn luyện tối đa là bao nhiêu? Quy định cũ có cho phép thi lại không?")
        self.assertIn("toi", terms)
        self.assertIn("da", terms)
        self.assertIn("thi", terms)
        self.assertIn("lai", terms)
        self.assertNotIn("la", terms)
        self.assertNotIn("bao", terms)
        self.assertNotIn("nhieu", terms)

    def test_academic_shorthand_and_synonyms_retrieve_the_right_clause(self):
        engine = HocVuEngine(self.config, self.searcher)
        cases = {
            "Điểm RL tối đa là bao nhiêu?": ("QD-RLSV-HPU-2026", "100 điểm"),
            "Nghỉ học bao nhiêu % thì bị cấm thi?": ("QD-DTDC-HPU-2026", "25%"),
            "Điều kiện để học song ngành là gì?": ("QD-DTDC-HPU-2026", "2.8"),
            "Điểm danh hộ bị xử lý ra sao?": ("QD-DTDC-HPU-2026", "trừ toàn bộ"),
        }
        for question, (rid, expected) in cases.items():
            with self.subTest(question=question):
                response = engine.ask(question, "synonyms", use_context=False, record_session=False)
                self.assertFalse(response.refused)
                self.assertEqual(response.references[0].rid, rid)
                self.assertIn(expected, response.answer)

    def test_coverage_uses_the_best_retrieved_clause_not_only_rank_one(self):
        engine = HocVuEngine(self.config, self.searcher)
        response = engine.ask("Điểm thực tập được tính như thế nào?", "coverage", use_context=False, record_session=False)
        self.assertFalse(response.refused)
        self.assertIn("40%", response.answer)
        self.assertEqual(response.references[0].rid, "QD-TTTN-HPU-2026")

    def test_numeric_inference_is_shown_with_its_source_formula(self):
        engine = HocVuEngine(self.config, self.searcher)
        response = engine.ask("Hiến máu 2 lần được cộng mấy điểm?", "numeric", use_context=False, record_session=False)
        self.assertFalse(response.refused)
        self.assertIn("2 lần × 10 điểm/lần = 20 điểm", response.answer)
        self.assertEqual(response.references[0].rid, "QD-RLSV-HPU-2026")

    def test_old_rule_can_be_retrieved_when_explicitly_requested(self):
        engine = HocVuEngine(self.config, self.searcher)
        response = engine.ask("Quy định cũ có cho phép thi lại không?", "historical", use_context=False, record_session=False)
        self.assertFalse(response.refused)
        self.assertEqual(response.references[0].rid, "QD-DTDC-HPU-2024")
        self.assertIn("thi lại 1 lần", response.answer)

    def test_comparison_uses_both_regulation_versions(self):
        engine = HocVuEngine(self.config, self.searcher)
        response = engine.ask("Quy định 2026 khác gì 2024 về thi lại?", "comparison", use_context=False, record_session=False)
        self.assertFalse(response.refused)
        self.assertEqual({reference.rid for reference in response.references}, {"QD-DTDC-HPU-2024", "QD-DTDC-HPU-2026"})
        self.assertIn("2024:", response.answer)
        self.assertIn("2026:", response.answer)
        self.assertIn("Không tổ chức thi lại", response.answer)

    def test_explains_absence_and_training_as_a_grounded_condition(self):
        question = "Tôi nghỉ 5 tiết học thì điểm rèn luyện bị ảnh hưởng như nào?"
        self.assertTrue(is_attendance_training_scenario(question))
        hits = self.searcher.search(expand_retrieval_query(question), 8, "2026-10-05")
        result = Generator(self.config).generate_attendance_training_scenario(hits, question)
        self.assertIsNotNone(result)
        answer, references = result
        self.assertIn("không quy định mức trừ", answer)
        self.assertIn("25%", answer)
        self.assertIn("5 tiết", answer)
        self.assertNotIn("3 tiết", answer)
        self.assertGreaterEqual(len(references), 2)

    def test_attendance_scenario_does_not_match_nghiep(self):
        self.assertFalse(is_attendance_training_scenario("Nghiệp vụ điểm rèn luyện có 3 tiết thực hành"))

    def test_bm25_refuses_a_query_with_only_generic_overlap(self):
        engine = HocVuEngine(self.config, self.searcher)
        engine.session = MagicMock()
        engine.session.contextualize.return_value = ("cho tôi biết thông tin chi tiết về tín chỉ xyzquux blabla nonsense", "")
        response = engine.ask("cho tôi biết thông tin chi tiết về tín chỉ xyzquux blabla nonsense", "test-refusal")
        self.assertTrue(response.refused)
        self.assertLess(response.confidence, self.config.lexical_coverage_floor)

    def test_rebuild_reuses_the_searcher_built_for_the_new_index(self):
        engine = HocVuEngine(self.config, self.searcher)
        replacement = HybridSearcher(self.config)
        with patch("core.engine.build_index", return_value=({"chunks": 1}, replacement)) as build:
            result = engine.rebuild_index()
        self.assertEqual(result["chunks"], 1)
        self.assertIs(engine.searcher, replacement)
        build.assert_called_once_with(self.config, return_searcher=True)

    def test_follow_up_uses_recent_academic_context(self):
        engine = HocVuEngine(self.config, self.searcher)
        engine.session = MagicMock()
        engine.session.get_history.return_value = [{"question": "Điều kiện bảo lưu là gì?"}]
        engine.session.contextualize.return_value = ("Điều kiện bảo lưu là gì? | Còn điều kiện nào khác?", "Điều kiện bảo lưu là gì?")
        response = engine.ask("Còn điều kiện nào khác?", "test-follow-up")
        self.assertFalse(response.refused)
        self.assertEqual(response.intent, Intent.ACADEMIC_RULES.value)

    def test_index_schema_version_is_saved_and_unknown_versions_fail_clearly(self):
        with tempfile.TemporaryDirectory() as directory:
            index_path = Path(directory) / "index.json"
            self.searcher.save(index_path)
            self.assertEqual(json.loads(index_path.read_text(encoding="utf-8"))["schema_version"], 2)
            index_path.write_text(json.dumps({"schema_version": 999, "chunks": []}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "schema version"):
                HybridSearcher.load(str(index_path), self.config)

    def test_corrupt_index_uses_last_atomic_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            index_path = Path(directory) / "index.json"
            self.searcher.save(index_path)
            self.searcher.save(index_path)
            index_path.write_text("{broken", encoding="utf-8")
            restored = HybridSearcher.load(str(index_path), self.config)
            self.assertEqual(len(restored.chunks), len(self.searcher.chunks))

    def test_api_response_hides_raw_retrieval_by_default(self):
        response = Response(query="q", answer="a", retrieved=self.searcher.search("bảo lưu", 1))
        self.assertNotIn("retrieved", response.to_dict())
        self.assertIn("retrieved", response.to_dict(include_retrieved=True))

    def test_empty_question_is_not_persisted(self):
        engine = HocVuEngine(self.config, self.searcher)
        engine.session = MagicMock()
        engine.ask("", "empty-session")
        engine.session.add_turn.assert_not_called()

    def test_semantic_query_error_falls_back_to_bm25(self):
        self.searcher.semantic = MagicMock()
        self.searcher.semantic.available = True
        self.searcher.semantic.similarities.side_effect = RuntimeError("model unavailable")
        hits = self.searcher.search("điều kiện bảo lưu", 1)
        self.assertTrue(hits)
        self.assertIsNone(self.searcher.semantic)
        self.assertIn("Semantic query fallback", self.searcher.semantic_error)

    def test_grounded_response_includes_structured_answer_card(self):
        engine = HocVuEngine(self.config, self.searcher)
        engine.session = MagicMock()
        engine.session.contextualize.return_value = ("Điều kiện bảo lưu kết quả học tập là gì?", "")
        response = engine.ask("Điều kiện bảo lưu kết quả học tập là gì?", "card-session")
        card = response.to_dict()["card"]
        self.assertTrue(response.references)
        self.assertTrue(card["verdict_segments"])
        self.assertEqual(card["verdict_segments"][0]["cites"], [1])
        self.assertGreaterEqual(card["grounding"]["level"], 2)
        self.assertEqual(card["grounding"]["source_count"], len(response.references))
        self.assertIn("answer", response.to_dict())
        self.assertIn("references", response.to_dict())

    def test_refusal_card_contains_answerable_suggestions(self):
        engine = HocVuEngine(self.config, self.searcher)
        engine.session = MagicMock()
        response = engine.ask("Con vịt có biết lập trình không?", "refusal-card", use_context=False)
        self.assertTrue(response.refused)
        self.assertEqual(len(response.card["suggestions"]), 3)
        self.assertNotIn("Con vịt có biết lập trình không?", response.card["suggestions"])
        suggested = {question for topic in engine.suggestion_topics() for question in topic["questions"]}
        self.assertTrue(set(response.card["suggestions"]).issubset(suggested))


if __name__ == "__main__":
    unittest.main()
