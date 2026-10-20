"""Content comparisons need both subjects, not two unrelated regulation IDs."""
from dataclasses import replace
import unittest
from unittest.mock import patch

from core.corpus import build_corpus
from core.engine import HocVuEngine
from core.generator import DECLINE_MSG, Generator
from core.scenarios import comparison_subjects, is_comparison_query, is_version_comparison_query
from core.searcher import HybridSearcher
from core.settings import AppConfig
from core.splitter import split_regulation


class ComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # A single-unit normal answer limit must not truncate an explicit pair.
        cls.config = AppConfig(semantic_enabled=False, max_units=1)
        cls.chunks = [chunk for regulation in build_corpus()
                      for chunk in split_regulation(regulation, 800, 1)]
        cls.searcher = HybridSearcher(cls.config)
        cls.searcher.build(cls.chunks)

    def ask(self, question, searcher=None, **kwargs):
        return HocVuEngine(self.config, searcher or self.searcher).ask(
            question, "comparison-test", ref_date="2026-10-20",
            use_context=False, record_session=False, **kwargs,
        )

    def test_content_comparison_does_not_imply_version_comparison(self):
        for question in (
            "So sánh học bổng loại Giỏi và Xuất sắc?",
            "Điểm thực tập và đồ án tốt nghiệp hệ kỹ sư khác nhau thế nào?",
            "Hoc bong loai Gioi khac gi Xuat sac?",
        ):
            with self.subTest(question=question):
                self.assertTrue(is_comparison_query(question))
                self.assertFalse(is_version_comparison_query(question))
                self.assertEqual(len(comparison_subjects(question)), 2)

    def test_explicit_version_comparisons_still_include_history(self):
        for question in (
            "Quy định 2026 khác gì 2024 về thi lại?",
            "So sánh quy định cũ và mới về thi lại?",
            "Điểm rèn luyện có thay đổi giữa các phiên bản quy định không?",
        ):
            with self.subTest(question=question):
                self.assertTrue(is_version_comparison_query(question))
                self.assertEqual(comparison_subjects(question), ())

    def test_scholarship_comparison_cites_both_clauses_in_the_same_article(self):
        for question in (
            "So sánh học bổng loại Giỏi và Xuất sắc?",
            "So sánh học bổng loại Xuất sắc với Giỏi?",
            "Học bổng loại Giỏi khác gì Xuất sắc?",
            "Học bổng loại Giỏi và Xuất sắc khác nhau như thế nào?",
            "Sự khác biệt giữa học bổng loại Giỏi và Xuất sắc?",
            "So sanh hoc bong loai Gioi va Xuat sac?",
            "So sánh học bổng Giỏi và Xuất sắc?",
        ):
            with self.subTest(question=question):
                response = self.ask(question)
                self.assertFalse(response.refused)
                self.assertIn("120%", response.answer)
                self.assertIn("150%", response.answer)
                self.assertNotIn("Chưa đủ các phiên bản", response.answer)
                self.assertEqual(
                    {(ref.rid, ref.aid, tuple(ref.clause_ids)) for ref in response.references},
                    {("QD-HBHT-HPU-2026", "Điều 2", ("1",)),
                     ("QD-HBHT-HPU-2026", "Điều 2", ("2",))},
                )

    def test_internship_and_engineering_project_cite_the_two_relevant_articles(self):
        for question in (
            "Điểm thực tập và đồ án tốt nghiệp hệ kỹ sư khác nhau thế nào?",
            "Diem thuc tap va do an tot nghiep he ky su khac nhau the nao?",
        ):
            with self.subTest(question=question):
                response = self.ask(question)
                self.assertFalse(response.refused)
                self.assertIn("40%", response.answer)
                self.assertIn("60%", response.answer)
                self.assertIn("14 tín chỉ", response.answer)
                self.assertIn("chưa nêu đầy đủ cách tính điểm", response.answer)
                self.assertEqual(
                    {(ref.rid, ref.aid, tuple(ref.clause_ids)) for ref in response.references},
                    {("QD-TTTN-HPU-2026", "Điều 2", ("2",)),
                     ("QD-TTTN-HPU-2026", "Điều 3", ("1",))},
                )

    def test_ordinary_comparison_keeps_date_filter_and_searches_each_subject(self):
        with patch.object(self.searcher, "search", wraps=self.searcher.search) as search:
            response = self.ask("So sánh học bổng loại Giỏi và Xuất sắc?")
        self.assertFalse(response.refused)
        self.assertEqual(search.call_count, 3)
        for call in search.call_args_list:
            self.assertFalse(call.kwargs["include_expired"])
            self.assertEqual(call.args[2], "2026-10-20")
            self.assertEqual(call.args[1], max(self.config.top_k, 20))

    def test_missing_side_does_not_borrow_graduation_classification(self):
        chunks = [chunk for chunk in self.chunks
                  if not (chunk.rid == "QD-HBHT-HPU-2026" and chunk.aid == "Điều 2"
                          and chunk.clause_ids == ["1"])]
        searcher = HybridSearcher(self.config)
        searcher.build(chunks)
        for question in (
            "So sánh học bổng loại Giỏi và Xuất sắc?",
            "So sánh học bổng Giỏi và Xuất sắc?",
        ):
            with self.subTest(question=question):
                response = self.ask(question, searcher)
                self.assertTrue(response.refused)
                self.assertEqual(response.references, [])
                self.assertNotIn("Chưa đủ các phiên bản", response.answer)

    def test_missing_side_and_unsupported_features_are_refused(self):
        for question in (
            "So sánh học bổng loại Giỏi và Quasar?",
            "So sánh học bổng loại Giỏi và Bóng đá?",
            "So sanh hoc bong loai Gioi va bong da?",
            "So sánh wifi ký túc xá và học phí?",
        ):
            with self.subTest(question=question):
                response = self.ask(question)
                self.assertTrue(response.refused)
                self.assertFalse(response.references)

    def test_expired_clause_cannot_supply_the_missing_side(self):
        chunks = [
            replace(chunk, valid_until="2026-09-30")
            if chunk.rid == "QD-HBHT-HPU-2026" and chunk.aid == "Điều 2"
            and chunk.clause_ids == ["1"] else chunk
            for chunk in self.chunks
        ]
        searcher = HybridSearcher(self.config)
        searcher.build(chunks)
        response = self.ask("So sánh học bổng loại Giỏi và Xuất sắc?", searcher)
        self.assertTrue(response.refused)
        self.assertFalse(response.references)
        self.assertTrue(all(hit.chunk.valid_until is None for hit in response.retrieved))

    def test_one_passage_may_cover_both_sides_without_duplicate_references(self):
        response = self.ask("So sánh xếp loại tốt nghiệp Giỏi và Xuất sắc?")
        self.assertFalse(response.refused)
        self.assertIn("3.60", response.answer)
        self.assertIn("3.20", response.answer)
        self.assertEqual(len(response.references), 1)
        self.assertEqual(response.references[0].rid, "QD-TTTN-HPU-2026")

    def test_generator_never_falls_back_to_one_sided_or_version_answer(self):
        question = "So sánh học bổng loại Giỏi và Xuất sắc?"
        hits = self.searcher.search(question, 30, "2026-10-20")
        hits = [hit for hit in hits if not (
            hit.chunk.rid == "QD-HBHT-HPU-2026" and hit.chunk.aid == "Điều 2"
            and hit.chunk.clause_ids == ["1"]
        )]
        self.assertEqual(Generator(self.config).generate(question, hits, comparison=True), (DECLINE_MSG, []))

    def test_version_comparison_keeps_both_versions(self):
        with patch.object(self.searcher, "search", wraps=self.searcher.search) as search:
            response = self.ask("Quy định 2026 khác gì 2024 về thi lại?")
        self.assertFalse(response.refused)
        self.assertEqual(
            {ref.rid for ref in response.references},
            {"QD-DTDC-HPU-2024", "QD-DTDC-HPU-2026"},
        )
        self.assertTrue(search.call_args.kwargs["include_expired"])
