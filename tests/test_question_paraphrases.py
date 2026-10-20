"""Trigger-vs-time and explicit pause/return paraphrases, with refusal guards."""
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.corpus import build_corpus
from core.engine import HocVuEngine
from core.nlp import expand_academic_terms
from core.question_focus import question_focus
from core.searcher import HybridSearcher
from core.settings import AppConfig
from core.splitter import split_regulation


class QuestionParaphraseTests(unittest.TestCase):
    warning = "Khi nào sinh viên năm nhất bị cảnh báo học vụ?"
    pause = "Muốn nghỉ một thời gian rồi quay lại học tiếp thì được nghỉ tối đa bao lâu?"

    @classmethod
    def setUpClass(cls):
        cls.config = AppConfig(semantic_enabled=False)
        cls.chunks = [chunk for regulation in build_corpus()
                      for chunk in split_regulation(regulation, 800, 1)]
        cls.searcher = cls.make_searcher(cls.chunks)

    @classmethod
    def make_searcher(cls, chunks):
        searcher = HybridSearcher(cls.config)
        searcher.build(chunks)
        return searcher

    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch("core.engine.SESSION_DB", root / "sessions.db"))
        self.enterContext(patch("core.engine.DOCS", root / "documents"))
        self.enterContext(patch("core.engine.AUD", root / "audio"))

    def ask(self, question, chunks=None):
        searcher = self.searcher if chunks is None else self.make_searcher(chunks)
        return HocVuEngine(self.config, searcher).ask(
            question, "paraphrases", ref_date="2026-10-20",
            use_ai=False, use_context=False, record_session=False,
        )

    def test_warning_when_question_uses_the_condition_clause(self):
        for question in (self.warning, "Khi nao sinh vien nam nhat bi canh bao hoc vu?"):
            with self.subTest(question=question):
                response = self.ask(question)
                self.assertFalse(response.refused)
                self.assertIn("dưới 1.2 đối với năm nhất", response.answer)
                self.assertEqual(
                    [(ref.rid, ref.aid, ref.clause_ids) for ref in response.references],
                    [("QD-DTDC-HPU-2026", "Điều 7", ["1"])],
                )

    def test_warning_threshold_is_source_driven(self):
        rule = next(c for c in self.chunks
                    if c.rid == "QD-DTDC-HPU-2026" and c.aid == "Điều 7" and c.clause_ids == ["1"])
        response = self.ask(self.warning, [replace(rule, text=rule.text.replace("1.2", "1.1"))])
        self.assertFalse(response.refused)
        self.assertIn("dưới 1.1 đối với năm nhất", response.answer)
        self.assertNotIn("1.2", response.answer)

    def test_warning_cannot_borrow_an_effectivity_date_or_another_condition(self):
        absent = [c for c in self.chunks
                  if not (c.rid == "QD-DTDC-HPU-2026" and c.aid == "Điều 7" and c.clause_ids == ["1"])]
        self.assertTrue(self.ask(self.warning, absent).refused)
        rule = next(c for c in self.chunks if c.rid == "QD-DTDC-HPU-2026" and c.aid == "Điều 7")
        metadata = replace(rule, text="Cảnh báo học vụ dành cho sinh viên năm nhất có hiệu lực từ ngày 2026-09-01.")
        self.assertTrue(self.ask(self.warning, [metadata]).refused)

    def test_explicit_pause_and_return_uses_bao_luu_duration(self):
        for question in (
            self.pause,
            "Muon nghi mot thoi gian roi quay lai hoc tiep thi duoc nghi toi da bao lau?",
            "Muốn nghỉ học tạm thời sau đó trở lại học tiếp thì được nghỉ tối đa bao lâu?",
        ):
            with self.subTest(question=question):
                response = self.ask(question)
                self.assertFalse(response.refused)
                self.assertIn("4 học kỳ", response.answer)
                self.assertEqual(
                    [(ref.rid, ref.aid, ref.clause_ids) for ref in response.references],
                    [("QD-DTDC-HPU-2026", "Điều 5", ["1"])],
                )

    def test_pause_duration_is_source_driven_and_missing_rule_refuses(self):
        rule = next(c for c in self.chunks
                    if c.rid == "QD-DTDC-HPU-2026" and c.aid == "Điều 5" and c.clause_ids == ["1"])
        response = self.ask(self.pause, [replace(rule, text=rule.text.replace("4 học kỳ", "6 học kỳ"))])
        self.assertFalse(response.refused)
        self.assertIn("6 học kỳ", response.answer)
        self.assertNotIn("4 học kỳ", response.answer)
        self.assertTrue(self.ask(self.pause, [c for c in self.chunks if c is not rule]).refused)

    def test_new_framing_preserves_unsupported_features(self):
        for question in (
            self.warning.replace("học vụ", "học vụ do wifi Quasar"),
            self.pause.replace("học tiếp", "học tiếp theo chương trình Quasar"),
        ):
            with self.subTest(question=question):
                self.assertTrue(self.ask(question).refused)

    def test_pause_normalization_is_narrow_and_idempotent(self):
        expanded = expand_academic_terms(self.pause)
        self.assertIn("bảo lưu", expanded)
        self.assertEqual(expand_academic_terms(expanded), expanded)
        self.assertIn("vắng mặt", expand_academic_terms("Nghỉ 2 buổi học thì sao?"))
        for question in (
            "Nghỉ 2 buổi học thì sao?",
            "Nghỉ một buổi rồi quay lại học tiếp thì sao?",
            "Muốn nghĩ một thời gian rồi quay lại học tiếp thì sao?",
        ):
            with self.subTest(question=question):
                self.assertNotIn("bảo lưu", expand_academic_terms(question))

    def test_calendar_and_duration_questions_keep_their_facets(self):
        self.assertEqual(question_focus(self.warning).kind, "trigger")
        self.assertEqual(question_focus("Bị đình chỉ học bao lâu?").kind, "timing")
        self.assertEqual(question_focus("Khi nào học bổng được phát?").kind, "payment_time")
        response = self.ask("Khi nào học bổng được phát?")
        self.assertFalse(response.refused)
        self.assertIn("tuần thứ 6", response.answer)
