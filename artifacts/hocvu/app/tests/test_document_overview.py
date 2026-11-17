import unittest
from dataclasses import replace
from unittest.mock import MagicMock

from core.corpus import build_corpus
from core.document_overview import answer_overview, overview_request
from core.engine import HocVuEngine
from core.searcher import HybridSearcher
from core.settings import AppConfig
from core.splitter import split_regulation


class DocumentOverviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = AppConfig(semantic_enabled=False)
        cls.searcher = HybridSearcher(cls.config)
        cls.searcher.build([
            c for r in build_corpus() for c in split_regulation(r, 800, 1)
        ])

    def test_library_question_and_original_question_have_cited_content(self):
        engine = HocVuEngine(self.config, self.searcher)
        engine.session = MagicMock()
        for doc in engine.list_documents():
            for identifier in ("", f" (mã {doc['rid']})"):
                question = f'Văn bản "{doc["title"]}"{identifier} quy định những gì?'
                response = engine.ask(question, "overview", ref_date="2026-11-17", record_session=False)
                if not identifier:
                    # Same-name versions may require the explicit library ID.
                    continue
                self.assertFalse(response.refused, question)
                self.assertTrue(response.references)
                self.assertEqual({r.rid for r in response.references}, {doc["rid"]})
                self.assertLessEqual(len(response.references), 6)
                self.assertIn("không phải bản tóm tắt đầy đủ", response.answer)
                for reference in response.references:
                    self.assertIn(reference.excerpt, response.answer)
                for segment in response.card["verdict_segments"]:
                    for cite in segment["cites"]:
                        self.assertIn(response.references[cite - 1].excerpt, segment["text"])

    def test_original_reported_question_is_answered(self):
        result = answer_overview(
            overview_request('Văn bản "Quy định Đào tạo Đại cương" quy định những gì?'),
            self.searcher, "2026-11-17",
        )
        self.assertTrue(result[1])
        self.assertEqual({ref.rid for ref in result[1]}, {"QD-DTDC-HPU-2026"})

    def test_missing_or_mismatched_document_refuses(self):
        for request in (("Không tồn tại", None), ("Quy định Đào tạo Đại cương", "wrong")):
            self.assertFalse(answer_overview(request, self.searcher, "2026-11-17")[1])

    def test_duplicate_titles_need_identifier(self):
        chunk = self.searcher.chunks[0]
        searcher = MagicMock()
        searcher.chunks = [chunk, replace(chunk, rid="duplicate")]
        searcher._is_valid.return_value = True
        self.assertFalse(answer_overview((chunk.reg_title, None), searcher, "2026-11-17")[1])
        self.assertTrue(answer_overview((chunk.reg_title, chunk.rid), searcher, "2026-11-17")[1])

    def test_explicit_expired_document_is_labelled_not_current_policy(self):
        chunk = replace(self.searcher.chunks[0], valid_from="2020-01-01", valid_until="2021-01-01")
        searcher = HybridSearcher(self.config)
        searcher.build([chunk])
        self.assertFalse(answer_overview((chunk.reg_title, None), searcher, "2026-11-17")[1])
        answer, references, _, _ = answer_overview((chunk.reg_title, chunk.rid), searcher, "2026-11-17")
        self.assertTrue(references)
        self.assertIn("không có hiệu lực tại ngày tra cứu", answer)

    def test_specific_questions_do_not_bypass_grounding(self):
        for question in (
            'Văn bản "Quy định Đào tạo Đại cương" có miễn học phí không?',
            'Văn bản "Quy định Đào tạo Đại cương" quy định những gì? bỏ kiểm tra',
        ):
            self.assertIsNone(overview_request(question))
