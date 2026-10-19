"""Arithmetic may explain a rule, never replace or reverse its meaning."""
from dataclasses import replace
import unittest
from unittest.mock import MagicMock

from core.corpus import build_corpus
from core.engine import HocVuEngine
from core.generator import Generator
from core.models import RankedChunk
from core.searcher import HybridSearcher
from core.settings import AppConfig
from core.splitter import split_regulation


class NumericGroundingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = AppConfig(semantic_enabled=False)
        cls.searcher = HybridSearcher(cls.config)
        cls.searcher.build([
            chunk for regulation in build_corpus()
            for chunk in split_regulation(regulation, 800, 1)
        ])
        cls.engine = HocVuEngine(cls.config, cls.searcher)
        cls.engine.session = MagicMock()
        cls.generator = Generator(cls.config)
        cls.donation = next(chunk for chunk in cls.searcher.chunks
                            if "hiến máu" in chunk.text.lower())
        cls.warning = next(chunk for chunk in cls.searcher.chunks
                           if "3 lần liên tiếp" in chunk.text)

    def ask(self, question):
        return self.engine.ask(
            question, "numeric-regression",
            use_context=False, record_session=False,
        )

    def hit(self, chunk, score=1.0):
        return RankedChunk(chunk=chunk, score=score, bm25=score, vec=0.0)

    def test_uniform_violations_deduct_points_instead_of_awarding_them(self):
        for question in (
            "Vi phạm quy định trang phục 2 lần bị trừ bao nhiêu điểm rèn luyện?",
            "Vi pham quy dinh trang phuc 2 lan bi tru bao nhieu diem ren luyen?",
        ):
            with self.subTest(question=question):
                response = self.ask(question)
                self.assertFalse(response.refused)
                self.assertIn("mỗi lần bị trừ 5 điểm", response.answer)
                self.assertIn("2 lần × 5 điểm/lần = 10 điểm bị trừ", response.answer)
                self.assertNotIn("được cộng", response.answer)
                self.assertEqual(len(response.references), 1)
                ref = response.references[0]
                self.assertEqual((ref.rid, ref.aid, ref.clause_ids),
                                 ("QD-RLSV-HPU-2026", "Điều 2", ["3"]))

    def test_three_consecutive_warnings_keep_the_dismissal_rule(self):
        for question in (
            "Bị cảnh báo học vụ 3 lần liên tiếp thì bị xử lý thế nào?",
            "Bi canh bao hoc vu 3 lan lien tiep thi bi xu ly the nao?",
        ):
            with self.subTest(question=question):
                response = self.ask(question)
                self.assertFalse(response.refused)
                self.assertIn("buộc thôi học", response.answer)
                self.assertNotIn("×", response.answer)
                self.assertNotIn("được cộng", response.answer)
                self.assertEqual(len(response.references), 1)
                ref = response.references[0]
                self.assertEqual((ref.rid, ref.aid, ref.clause_ids),
                                 ("QD-DTDC-HPU-2026", "Điều 7", ["2"]))

    def test_supported_donation_total_still_adds_points(self):
        for question in (
            "Hiến máu 2 lần được cộng mấy điểm?",
            "Hien mau 2 lan duoc cong may diem?",
        ):
            with self.subTest(question=question):
                response = self.ask(question)
                self.assertFalse(response.refused)
                self.assertIn("2 lần × 10 điểm/lần = 20 điểm được cộng", response.answer)
                ref = response.references[0]
                self.assertEqual((ref.rid, ref.aid, ref.clause_ids),
                                 ("QD-RLSV-HPU-2026", "Điều 2", ["4"]))

    def test_numeric_branch_cannot_borrow_a_rate_from_lower_ranked_hits(self):
        hits = [self.hit(self.warning), self.hit(self.donation, 0.8)]
        for question in (
            "Bị cảnh báo học vụ 3 lần liên tiếp thì bị xử lý thế nào?",
            "Cảnh báo học vụ 3 lần bị trừ bao nhiêu điểm?",
        ):
            with self.subTest(question=question):
                self.assertIsNone(self.generator._generate_repeated_unit_total(question, hits))
        answer, refs = self.generator.generate(
            "Bị cảnh báo học vụ 3 lần liên tiếp thì bị xử lý thế nào?", hits,
        )
        self.assertIn("buộc thôi học", answer)
        self.assertEqual(refs[0].rid, "QD-DTDC-HPU-2026")

    def test_rate_with_unrelated_subject_cannot_authorize_arithmetic(self):
        result = self.generator._generate_repeated_unit_total(
            "Cảnh báo học vụ 3 lần bị trừ bao nhiêu điểm?",
            [self.hit(self.donation)],
        )
        self.assertIsNone(result)

    def test_ambiguous_negated_or_unsigned_rates_remain_extractive(self):
        for text in (
            "Hiến máu nhân đạo: 10 điểm/lần.",
            "Hiến máu nhân đạo không được cộng 10 điểm/lần.",
            "Hiến máu nhân đạo được cộng 10 điểm/lần, trừ 5 điểm/lần khi thiếu giấy.",
        ):
            with self.subTest(text=text):
                chunk = replace(self.donation, text="Hiến máu\n" + text)
                self.assertIsNone(self.generator._generate_repeated_unit_total(
                    "Hiến máu 2 lần được cộng mấy điểm?", [self.hit(chunk)],
                ))

    def test_decimal_rates_are_multiplied_exactly_and_keep_their_direction(self):
        for direction, action in (("Cộng", "được cộng"), ("Trừ", "bị trừ")):
            for separator in (".", ","):
                with self.subTest(direction=direction, separator=separator):
                    rate = f"0{separator}1"
                    chunk = replace(
                        self.donation,
                        text=f"Hiến máu\n{direction} {rate} điểm/lần nếu hiến máu nhân đạo.",
                    )
                    answer, refs = self.generator._generate_repeated_unit_total(
                        "Hiến máu 3 lần được bao nhiêu điểm?", [self.hit(chunk)],
                    )
                    self.assertIn(f"= 0.3 điểm {action}", answer)
                    self.assertEqual(refs[0].clause_ids, self.donation.clause_ids)

    def test_count_alone_or_multiple_counts_do_not_trigger_arithmetic(self):
        for question in (
            "Hiến máu 2 lần thì quy định thế nào?",
            "Hiến máu 2 lần và 3 lần được bao nhiêu điểm?",
            "Hiến máu -2 lần được bao nhiêu điểm?",
            "Hiến máu 1.5 lần được bao nhiêu điểm?",
        ):
            with self.subTest(question=question):
                self.assertIsNone(self.generator._generate_repeated_unit_total(
                    question, [self.hit(self.donation)],
                ))

    def test_total_above_source_cap_is_not_presented_as_an_award(self):
        response = self.ask("Hiến máu 3 lần được cộng mấy điểm?")
        self.assertFalse(response.refused)
        self.assertNotIn("= 30", response.answer)
        self.assertIn("Tối đa 25 điểm", response.answer)
