"""Reported failures plus counterexamples: never improve recall by guessing."""
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.corpus import build_corpus
from core.engine import HocVuEngine
from core.generator import Generator
from core.numeric_conditions import numeric_verdict
from core.question_focus import question_focus
from core.scenarios import comparison_topic, is_version_comparison_query
from core.searcher import HybridSearcher
from core.settings import AppConfig
from core.splitter import split_regulation


class ReportRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = AppConfig(semantic_enabled=False)
        cls.chunks = [chunk for regulation in build_corpus()
                      for chunk in split_regulation(regulation, 800, 1)]
        cls.searcher = HybridSearcher(cls.config)
        cls.searcher.build(cls.chunks)

    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch("core.engine.SESSION_DB", root / "sessions.db"))
        self.enterContext(patch("core.engine.DOCS", root / "documents"))
        self.enterContext(patch("core.engine.AUD", root / "audio"))
        self.engine = HocVuEngine(self.config, self.searcher)

    def ask(self, question, *, searcher=None, ref_date="2026-10-20"):
        engine = HocVuEngine(self.config, searcher) if searcher else self.engine
        return engine.ask(question, "report", ref_date=ref_date, use_context=False, record_session=False)

    def with_chunks(self, chunks):
        searcher = HybridSearcher(self.config)
        searcher.build(chunks)
        return searcher

    def test_effectivity_and_current_version_use_document_evidence(self):
        for question in (
            "Quy định đào tạo đại cương có hiệu lực từ khi nào?",
            "Quy định đào tạo đại cương nào đang có hiệu lực hiện tại?",
            "Quy định đào tạo đại cương hiện hành là bản nào?",
            "Quy dinh dao tao dai cuong hien hanh la ban nao?",
        ):
            with self.subTest(question=question):
                response = self.ask(question)
                self.assertFalse(response.refused)
                self.assertIn("2026-09-01", response.answer)
                self.assertIn("QD-DTDC-HPU-2026", response.answer)
                self.assertEqual({ref.rid for ref in response.references}, {"QD-DTDC-HPU-2026"})
                self.assertIn("2026-09-01", response.references[0].excerpt)

    def test_metadata_lookup_keeps_the_requested_date_and_unknown_subjects(self):
        old = self.ask("Quy định đào tạo đại cương hiện hành là bản nào?", ref_date="2024-10-20")
        self.assertFalse(old.refused)
        self.assertEqual({ref.rid for ref in old.references}, {"QD-DTDC-HPU-2024"})
        for question in (
            "Quy định wifi đào tạo đại cương có hiệu lực từ khi nào?",
            "Quy định Quasar hiện hành là bản nào?",
        ):
            with self.subTest(question=question):
                self.assertTrue(self.ask(question).refused)

    def test_metadata_only_dates_are_not_hardcoded_or_guessed(self):
        base = next(chunk for chunk in self.chunks if chunk.rid == "QD-DTDC-HPU-2026")
        chunk = replace(base, rid="SYNTHETIC", version="release-A", valid_from="2026-02-12",
                        art_heading="Thông tin chung", text="Văn bản được lưu trong kho.")
        question = "Quy định đào tạo đại cương có hiệu lực từ khi nào?"
        response = self.ask(question, searcher=self.with_chunks([chunk]))
        self.assertFalse(response.refused)
        self.assertIn("2026-02-12", response.answer)
        self.assertIn("release-A", response.answer)
        for value in ("2027-01-01", "2026-02-30", ""):
            with self.subTest(valid_from=value):
                response = self.ask(question, searcher=self.with_chunks([replace(chunk, valid_from=value)]))
                self.assertTrue(response.refused)
                self.assertFalse(response.references)

    def test_version_comparisons_keep_both_years_and_correct_credit_values(self):
        for question, values in (
            ("TOEIC tối thiểu năm 2024 và 2026 khác nhau ra sao?", ("350", "450")),
            ("Số tín chỉ đại cương bản cũ và bản mới?", ("35 tín chỉ", "45 tín chỉ")),
            ("So tin chi dai cuong ban cu va ban moi?", ("35 tín chỉ", "45 tín chỉ")),
        ):
            with self.subTest(question=question):
                self.assertTrue(is_version_comparison_query(question))
                response = self.ask(question)
                self.assertFalse(response.refused)
                self.assertEqual({ref.rid for ref in response.references},
                                 {"QD-DTDC-HPU-2024", "QD-DTDC-HPU-2026"})
                for value in values:
                    self.assertIn(value, response.answer)

    def test_version_framing_never_strips_an_unsupported_feature(self):
        for question in (
            "Wifi ký túc xá năm 2024 và 2026 khác nhau ra sao?",
            "Wifi ký túc xá có thay đổi giữa các phiên bản quy định không?",
        ):
            with self.subTest(question=question):
                self.assertIn("wifi", comparison_topic(question).lower())
                self.assertTrue(self.ask(question).refused)

    def test_scholarship_conditions_include_the_named_category_and_common_rule(self):
        response = self.ask("Muốn được học bổng loại Giỏi cần những điều kiện gì?")
        self.assertFalse(response.refused)
        for value in ("3.2", "3.59", "80", "15 tín chỉ"):
            self.assertIn(value, response.answer)
        self.assertNotIn("150%", response.answer)
        self.assertEqual({tuple(ref.clause_ids) for ref in response.references}, {("2",), ("4",)})
        self.assertTrue(self.ask("Muốn được học bổng loại Quasar cần những điều kiện gì?").refused)

    def test_forgetting_homework_cannot_borrow_a_training_score_penalty(self):
        for question in (
            "Quên làm bài tập về nhà có bị trừ điểm rèn luyện không?",
            "Quen lam bai tap ve nha co bi tru diem ren luyen khong?",
        ):
            with self.subTest(question=question):
                response = self.ask(question)
                self.assertTrue(response.refused)
                self.assertFalse(response.references)

    def test_payment_time_has_a_time_and_the_scholarship_subject(self):
        response = self.ask("Học bổng được phát vào thời gian nào?")
        self.assertFalse(response.refused)
        self.assertIn("tuần thứ 6", response.answer)
        self.assertIn("chuyển khoản", response.answer)
        self.assertEqual({(ref.rid, ref.aid) for ref in response.references}, {("QD-HBHT-HPU-2026", "Điều 5")})
        absent = [chunk for chunk in self.chunks
                  if not (chunk.rid == "QD-HBHT-HPU-2026" and chunk.aid == "Điều 5")]
        self.assertTrue(self.ask("Học bổng được phát vào thời gian nào?", searcher=self.with_chunks(absent)).refused)

    def test_training_score_is_the_cause_of_suspension_not_an_effect_of_cheating(self):
        response = self.ask("Bị đình chỉ học vì điểm rèn luyện kém trong trường hợp nào?")
        self.assertFalse(response.refused)
        self.assertIn("Yếu trong 2 học kỳ liên tiếp", response.answer)
        self.assertNotIn("gian lận", response.answer)
        self.assertEqual(response.references[0].aid, "Điều 4")
        absent = [chunk for chunk in self.chunks
                  if not (chunk.rid == "QD-RLSV-HPU-2026" and chunk.aid == "Điều 4")]
        self.assertTrue(self.ask("Bị đình chỉ học vì điểm rèn luyện kém trong trường hợp nào?",
                                 searcher=self.with_chunks(absent)).refused)

    def test_amount_is_monetary_and_best_merit_award_is_not_dormitory_priority(self):
        response = self.ask("Tiền thưởng cho sinh viên học giỏi nhất là bao nhiêu?")
        self.assertFalse(response.refused)
        self.assertIn("150%", response.answer)
        self.assertIn("3.6", response.answer)
        self.assertNotIn("Ký túc xá", response.answer)
        self.assertEqual({ref.rid for ref in response.references}, {"QD-HBHT-HPU-2026"})

    def test_actor_question_cites_the_actual_evaluation_process(self):
        for question in ("Ai là người chấm điểm rèn luyện cho sinh viên?",
                         "Ai la nguoi cham diem ren luyen cho sinh vien?"):
            with self.subTest(question=question):
                response = self.ask(question)
                self.assertFalse(response.refused)
                for actor in ("Cá nhân sinh viên", "Tập thể lớp", "Hội đồng khoa"):
                    self.assertIn(actor, response.answer)
                self.assertEqual(response.references[0].aid, "Điều 7")

    def test_fixed_cash_awards_are_not_described_as_percentages(self):
        base = next(chunk for chunk in self.chunks if chunk.rid == "QD-HBHT-HPU-2026")
        cash = replace(base, text="Thưởng 200000 đồng khi điểm học tập >= 3.6.",
                       art_heading="Mức thưởng", aid="Điều thử nghiệm", clause_ids=["cash"])
        response = self.ask("Tiền thưởng cao nhất là bao nhiêu?", searcher=self.with_chunks([cash]))
        self.assertFalse(response.refused)
        self.assertIn("200000 đồng", response.answer)
        self.assertNotIn("phần trăm", response.answer)
        self.assertNotIn("không phải một số tiền cố định", response.answer)

    def test_numeric_ineligibility_has_an_explicit_grounded_verdict(self):
        for question, detail in (
            ("TOEIC 400 có đủ điều kiện học tiếng Anh chuyên ngành không?", "TOEIC 400 < 450"),
            ("GPA 2.7 và 35 tín chỉ có được học song ngành không?", "GPA 2.7 < 2.8"),
        ):
            with self.subTest(question=question):
                response = self.ask(question)
                self.assertFalse(response.refused)
                self.assertTrue(response.answer.startswith("Không đủ điều kiện"))
                self.assertIn(detail, response.answer)
                self.assertEqual(response.card["verdict_segments"][0]["cites"], [1])

    def test_long_root_followup_stays_on_bao_luu_across_restart(self):
        first = "Điều kiện bảo lưu kết quả học tập là gì?"
        response = self.engine.ask(first, "long-root", ref_date="2026-10-20")
        self.assertFalse(response.refused)
        self.engine = HocVuEngine(self.config, self.searcher)
        response = self.engine.ask("còn điều kiện nào khác không?", "long-root", ref_date="2026-10-20")
        self.assertFalse(response.refused)
        self.assertEqual({(ref.rid, ref.aid) for ref in response.references}, {("QD-DTDC-HPU-2026", "Điều 5")})
        self.assertNotIn("thực tập", response.answer)
        self.assertEqual(self.engine.history("long-root")[-1]["context_root"], first)

    def test_no_new_arithmetic_or_wrong_historical_assumptions(self):
        for question in (
            "Nghỉ 2 buổi học thì bị trừ mấy điểm rèn luyện?",
            "Bị khiển trách 2 lần thì bị trừ tổng cộng bao nhiêu điểm?",
            "TOEIC tối thiểu vào đầu năm 2024 là bao nhiêu?",
            "",
        ):
            with self.subTest(question=question):
                self.assertTrue(self.ask(question).refused)
        response = self.ask("Văn bản nào thay thế quy định QD-DTDC-HPU-2024?")
        self.assertFalse(response.refused)
        self.assertIn("QD-DTDC-HPU-2026", response.answer)
        self.assertTrue(response.references)

    def test_question_framing_keeps_compound_terms_and_unknown_features(self):
        for question, retained in (
            ("Điều kiện chuyên cần để dự thi là gì?", "chuyên cần"),
            ("Điều kiện công nhận tín chỉ là gì?", "công nhận"),
            ("Điều kiện nhận học bổng bóng đá là gì?", "bóng đá"),
        ):
            with self.subTest(question=question):
                self.assertIn(retained, question_focus(question).topic)

    def test_semantic_primary_cannot_borrow_another_hit_or_bypass_a_requested_facet(self):
        question = "Học bổng được phát vào thời gian nào?"
        hits = self.searcher.rerank_by_coverage(question, self.searcher.search(question, 20, "2026-10-20"))
        payment = next(hit for hit in hits if hit.chunk.rid == "QD-HBHT-HPU-2026" and hit.chunk.aid == "Điều 5")
        unrelated = next(hit for hit in hits if hit.chunk.rid == "QD-TTTN-HPU-2026")
        unrelated = replace(unrelated, score=100, vec=0.99)
        answer, refs = Generator(self.config).generate(question, [unrelated, payment])
        self.assertIn("tuần thứ 6", answer)
        self.assertEqual({ref.rid for ref in refs}, {"QD-HBHT-HPU-2026"})
        _, refs = Generator(self.config).generate(question, [unrelated])
        self.assertEqual(refs, [])


class NumericConditionTests(unittest.TestCase):
    def test_numeric_comparisons_are_source_driven_and_decimal_safe(self):
        rule = "Sinh viên phải đạt tối thiểu 470 điểm TOEIC để học chuyên ngành."
        for score, fails in (("469", True), ("470", False), ("471", False)):
            with self.subTest(score=score):
                verdict = numeric_verdict(f"TOEIC {score} có đủ điều kiện không?", rule)
                self.assertEqual(verdict.startswith("Không đủ"), fails)
                self.assertIn("470", verdict)
        rule = "Điểm trung bình tích lũy đạt từ 2.8 trở lên và tín chỉ tích lũy đạt từ 30 tín chỉ."
        self.assertIn("GPA 2.7 < 2.8", numeric_verdict("GPA 2,7 và 35 tín chỉ có được học song ngành không?", rule))
        self.assertIn("tín chỉ 29 < 30", numeric_verdict("GPA 3.0 và 29 tín chỉ có được học song ngành không?", rule))

    def test_exceptions_negation_and_ambiguous_measures_do_not_make_verdicts(self):
        question = "TOEIC 400 có đủ điều kiện không?"
        for body in (
            "Đạt tối thiểu 450 điểm TOEIC hoặc IELTS 5.5.",
            "Không yêu cầu tối thiểu 450 điểm TOEIC.",
            "Ví dụ tối thiểu 450 điểm TOEIC.",
            "Điều kiện học TOEIC sẽ được công bố sau.",
        ):
            with self.subTest(body=body):
                self.assertEqual(numeric_verdict(question, body), "")
        self.assertEqual(numeric_verdict(
            "TOEIC 400 và TOEIC 500 có đủ điều kiện không?", "Đạt tối thiểu 450 điểm TOEIC.",
        ), "")
        self.assertEqual(numeric_verdict(
            "GPA 2.5 có bị buộc thôi học không?", "Sinh viên bị buộc thôi học khi GPA dưới 2.0.",
        ), "")

    def test_intervals_and_strict_bounds(self):
        self.assertIn("GPA 3.6 > 3.59", numeric_verdict(
            "GPA 3.6 có đủ điều kiện không?", "Điểm học tập từ 3.2 đến 3.59.",
        ))
        self.assertIn("GPA 2.8 <= 2.8", numeric_verdict(
            "GPA 2.8 có đủ điều kiện không?", "Điểm trung bình tích lũy trên 2.8.",
        ))
