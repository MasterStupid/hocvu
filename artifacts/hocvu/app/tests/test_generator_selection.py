"""Ordinary answers honour max_units and choose the source after acceptance."""
from dataclasses import replace
import unittest

from core.generator import DECLINE_MSG, Generator
from core.models import Chunk, RankedChunk
from core.settings import AppConfig


class GeneratorSelectionTests(unittest.TestCase):
    question = "Điều kiện bảo lưu kết quả học tập"

    @staticmethod
    def hit(cid, text, *, rid="source", score=10.0, vec=0.0):
        return RankedChunk(
            chunk=Chunk(
                cid=cid, rid=rid, reg_title="Quy định", version="2026",
                valid_from="2026-01-01", valid_until=None,
                aid="Điều 1", art_heading="", clause_ids=[cid], text=text,
            ),
            score=score, bm25=score, vec=vec,
        )

    def relevant_hits(self):
        return [
            self.hit("1", "Điều kiện bảo lưu kết quả học tập: đã học ít nhất một học kỳ.", score=10),
            self.hit("2", "Điều kiện bảo lưu kết quả học tập: không thuộc diện buộc thôi học.", score=9),
            self.hit("3", "Điều kiện bảo lưu kết quả học tập: nộp đơn cho phòng đào tạo.", score=8),
        ]

    def test_max_units_one_two_and_three_are_effective(self):
        for limit in (1, 2, 3):
            with self.subTest(limit=limit):
                hits = self.relevant_hits()
                answer, refs = Generator(AppConfig(max_units=limit)).generate(self.question, hits)
                self.assertEqual(len(refs), limit)
                self.assertEqual([ref.clause_ids for ref in refs], [[str(i)] for i in range(1, limit + 1)])
                for index, hit in enumerate(hits):
                    self.assertEqual(hit.chunk.text in answer, index < limit)

    def test_rejected_first_hit_does_not_lock_the_wrong_source_or_score(self):
        hits = [
            self.hit("wrong", "Lịch tuyển sinh.", rid="wrong-source", score=1000),
            *self.relevant_hits(),
        ]
        answer, refs = Generator(AppConfig(max_units=2)).generate(self.question, hits)
        self.assertEqual([ref.rid for ref in refs], ["source", "source"])
        self.assertEqual([ref.clause_ids for ref in refs], [["1"], ["2"]])
        self.assertNotIn("Lịch tuyển sinh", answer)

    def test_later_hits_cannot_mix_a_different_source_into_normal_answers(self):
        first, second, _ = self.relevant_hits()
        foreign = replace(second, chunk=replace(second.chunk, rid="unrelated-source"))
        _, refs = Generator(AppConfig(max_units=2)).generate(self.question, [first, foreign, second])
        self.assertEqual([ref.rid for ref in refs], ["source", "source"])

    def test_weak_score_is_skipped_without_hiding_a_later_reranked_hit(self):
        first, second, _ = self.relevant_hits()
        weak = replace(second, chunk=replace(second.chunk, cid="weak"), score=5.4)
        answer, refs = Generator(AppConfig(max_units=2)).generate(self.question, [first, weak, second])
        self.assertEqual([ref.clause_ids for ref in refs], [["1"], ["2"]])
        self.assertEqual(answer.count(second.chunk.text), 1)

    def test_secondary_overlap_threshold_is_enforced(self):
        first, second, _ = self.relevant_hits()
        partial = self.hit("partial", "Bảo lưu kết quả.", score=9.5)
        answer, refs = Generator(AppConfig(max_units=2)).generate(self.question, [first, partial, second])
        self.assertEqual([ref.clause_ids for ref in refs], [["1"], ["2"]])
        self.assertNotIn(partial.chunk.text, answer)

    def test_secondary_passage_cannot_borrow_focus_support(self):
        question = "Wifi ở ký túc xá thế nào?"
        first = self.hit("1", "Ký túc xá có wifi miễn phí.", score=10)
        off_topic = self.hit("2", "Ký túc xá mở cửa từ 6 giờ đến 22 giờ.", score=9)
        answer, refs = Generator(AppConfig(max_units=2)).generate(question, [first, off_topic])
        self.assertEqual(len(refs), 1)
        self.assertNotIn("22 giờ", answer)

    def test_another_article_must_add_a_requested_aspect(self):
        first, second, _ = self.relevant_hits()
        second = replace(second, chunk=replace(second.chunk, aid="Điều 2"))
        answer, refs = Generator(AppConfig(max_units=2)).generate(self.question, [first, second])
        self.assertEqual(len(refs), 1)
        self.assertNotIn(second.chunk.text, answer)

    def test_quantity_framing_does_not_make_project_credits_complementary(self):
        first = self.hit("1", "Tốt nghiệp cần đủ 130 tín chỉ cử nhân.", score=10)
        second = self.hit("2", "Đồ án tốt nghiệp tương đương 10 tín chỉ hệ cử nhân.", score=9)
        second = replace(second, chunk=replace(second.chunk, aid="Điều 2"))
        question = "Số tín chỉ tốt nghiệp hệ cử nhân là bao nhiêu?"
        answer, refs = Generator(AppConfig(max_units=2)).generate(question, [first, second])
        self.assertEqual(len(refs), 1)
        self.assertNotIn("10 tín chỉ", answer)

    def test_complementary_articles_from_one_source_can_both_be_selected(self):
        first = self.hit("1", "Điều kiện bảo lưu kết quả học tập: đã học ít nhất một học kỳ.", score=10)
        second = self.hit("2", "Thời hạn bảo lưu kết quả học tập: tối đa hai năm.", score=9)
        second = replace(second, chunk=replace(second.chunk, aid="Điều 2"))
        question = "Điều kiện và thời hạn bảo lưu kết quả học tập"
        answer, refs = Generator(AppConfig(max_units=2)).generate(question, [first, second])
        self.assertEqual([ref.aid for ref in refs], ["Điều 1", "Điều 2"])
        self.assertIn("hai năm", answer)

    def test_complementary_article_can_supply_more_than_one_clause(self):
        first = self.hit("1", "Điều kiện bảo lưu kết quả học tập: đã học ít nhất một học kỳ.", score=10)
        second = self.hit("2", "Thời hạn bảo lưu kết quả học tập: tối đa hai năm.", score=9)
        third = self.hit("3", "Thời hạn bảo lưu kết quả học tập được ghi trong quyết định.", score=8)
        second = replace(second, chunk=replace(second.chunk, aid="Điều 2"))
        third = replace(third, chunk=replace(third.chunk, aid="Điều 2"))
        question = "Điều kiện và thời hạn bảo lưu kết quả học tập"
        _, refs = Generator(AppConfig(max_units=3)).generate(question, [first, second, third])
        self.assertEqual([ref.aid for ref in refs], ["Điều 1", "Điều 2", "Điều 2"])

    def test_semantic_evidence_can_select_the_primary_source(self):
        first = self.hit("semantic", "Được tạm ngừng học theo quyết định của trường.", vec=0.9)
        answer, refs = Generator(AppConfig(max_units=1)).generate(self.question, [first])
        self.assertEqual(answer, first.chunk.text)
        self.assertEqual(len(refs), 1)

    def test_semantically_supported_additional_passage_keeps_lexical_safety(self):
        first = self.hit("1", "Điều kiện bảo lưu: nộp hồ sơ tại phòng đào tạo.", score=10, vec=0.9)
        second = self.hit("2", "Bảo lưu: thời gian tạm ngừng tối đa hai năm.", score=9, vec=0.9)
        answer, refs = Generator(AppConfig(max_units=2)).generate("Điều kiện bảo lưu", [first, second])
        self.assertEqual(len(refs), 2)
        self.assertIn("hai năm", answer)

    def test_duplicate_hit_does_not_use_up_a_unit(self):
        first, second, _ = self.relevant_hits()
        _, refs = Generator(AppConfig(max_units=2)).generate(self.question, [first, first, second])
        self.assertEqual([ref.clause_ids for ref in refs], [["1"], ["2"]])

    def test_no_qualifying_hit_still_refuses(self):
        hits = [self.hit("wrong", "Lịch tuyển sinh.")]
        self.assertEqual(Generator(AppConfig(max_units=2)).generate(self.question, hits), (DECLINE_MSG, []))
        self.assertEqual(Generator(AppConfig(max_units=2)).generate(self.question, []), (DECLINE_MSG, []))
