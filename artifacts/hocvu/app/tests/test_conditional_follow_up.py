"""A named condition may refine the previous topic only through one shared clause."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.engine import HocVuEngine
from core.models import Article, Clause, Regulation
from core.scenarios import is_conditional_follow_up, is_context_dependent, is_contextual_follow_up
from core.searcher import HybridSearcher
from core.settings import AppConfig
from core.splitter import split_regulation

SCHOLARSHIP = "Điều kiện xét học bổng khuyến khích học tập là gì?"
CONDITION = "Nếu em có một môn phải học lại thì sao?"


def regulations(*, linked: bool) -> list[Regulation]:
    scholarship = [
        Clause("1", "Sinh viên được xét học bổng khuyến khích học tập khi đăng ký tối thiểu 15 tín chỉ trong học kỳ xét."),
    ]
    if linked:
        scholarship.append(Clause(
            "2", "Sinh viên có học phần phải học lại trong học kỳ xét thì không được xét học bổng khuyến khích học tập.",
        ))
    return [
        Regulation(
            "HB-TEST", "Quy định học bổng thử nghiệm", "Quy định", "2026", "2026-01-01", None, "Phòng Đào tạo",
            [Article("Điều 2", "Điều kiện xét học bổng khuyến khích học tập", scholarship)],
        ),
        Regulation(
            "HL-TEST", "Quy định thi và học lại thử nghiệm", "Quy định", "2026", "2026-01-01", None, "Phòng Đào tạo",
            [Article("Điều 4", "Thi lại và học lại", [
                Clause("1", "Sinh viên có điểm học phần dưới 4.0 phải đăng ký học lại học phần đó."),
                Clause("2", "Sinh viên phải học lại một môn thì đăng ký lớp học lại trong học kỳ kế tiếp."),
            ])],
        ),
    ]


def make_engine(root: Path, *, linked: bool) -> HocVuEngine:
    config = AppConfig(semantic_enabled=False)
    searcher = HybridSearcher(config)
    searcher.build([
        chunk for regulation in regulations(linked=linked)
        for chunk in split_regulation(regulation, 800, 1)
    ])
    with patch("core.engine.SESSION_DB", root / "sessions.db"), patch("core.engine.DOCS", root / "docs"):
        return HocVuEngine(config, searcher)


class ConditionalRecognitionTests(unittest.TestCase):
    def test_open_conditions_are_recognised_with_and_without_accents(self):
        for question in (
            CONDITION, "Neu em co mot mon phai hoc lai thi sao", "Giả sử em nghỉ học một kỳ thì thế nào ạ?",
            "Trường hợp em bị kỷ luật thì có sao không?", "Lỡ em nợ học phí thì ra sao nhỉ?",
        ):
            with self.subTest(question=question):
                self.assertTrue(is_conditional_follow_up(question))
                # It names its own subject, so it is never a bare reference.
                self.assertFalse(is_context_dependent(question))

    def test_ordinary_questions_and_bare_references_are_unchanged(self):
        for question in (
            "Học phí thì sao?", "Nếu vậy thì sao?", "Thì sao?", "Nếu thì sao?",
            "Điều kiện xét học bổng là gì?", "Nếu em học lại có được xét học bổng không?", "",
        ):
            with self.subTest(question=question):
                self.assertFalse(is_conditional_follow_up(question))
        self.assertTrue(is_contextual_follow_up("Nếu vậy thì sao?"))


class ConditionalFollowUpTests(unittest.TestCase):
    def engine(self, *, linked: bool) -> HocVuEngine:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return make_engine(Path(directory.name), linked=linked)

    def test_shared_clause_answers_within_the_previous_topic(self):
        engine = self.engine(linked=True)
        self.assertFalse(engine.ask(SCHOLARSHIP, "conversation").refused)
        response = engine.ask(CONDITION, "conversation")
        self.assertFalse(response.refused, response.answer)
        self.assertEqual({(ref.rid, ref.aid) for ref in response.references}, {("HB-TEST", "Điều 2")})
        self.assertIn("không được xét học bổng", response.answer)
        self.assertNotIn("HocVu trả lời riêng", str(response.card["notes"]))
        saved = engine.history("conversation")[-1]
        self.assertEqual(saved["context_root"], SCHOLARSHIP)
        self.assertEqual(saved["context_question"], f"{SCHOLARSHIP} | {CONDITION}")

    def test_without_a_shared_clause_the_answer_stands_alone_and_says_so(self):
        engine = self.engine(linked=False)
        self.assertFalse(engine.ask(SCHOLARSHIP, "conversation").refused)
        standalone = engine.ask(CONDITION, "standalone", record_session=False)
        response = engine.ask(CONDITION, "conversation")
        self.assertFalse(response.refused, response.answer)
        # History supplied no evidence: same answer and sources as a new chat.
        self.assertEqual(response.answer, standalone.answer)
        self.assertEqual(response.references, standalone.references)
        self.assertEqual({ref.rid for ref in response.references}, {"HL-TEST"})
        note = response.card["notes"][0]["text"]
        self.assertIn("chưa tìm thấy điều khoản nối", note)
        self.assertIn(SCHOLARSHIP, note)
        self.assertEqual(standalone.card["notes"], response.card["notes"][1:])
        self.assertEqual(engine.history("conversation")[-1]["context_root"], CONDITION)

    def test_no_previous_grounded_answer_means_no_note_and_no_borrowing(self):
        engine = self.engine(linked=True)
        self.assertTrue(engine.ask("Giá vàng hôm nay?", "conversation").refused)
        response = engine.ask(CONDITION, "conversation")
        standalone = engine.ask(CONDITION, "standalone", record_session=False)
        self.assertEqual(response.answer, standalone.answer)
        self.assertEqual(response.card["notes"], standalone.card["notes"])

    def test_unsupported_condition_is_still_refused(self):
        engine = self.engine(linked=True)
        engine.ask(SCHOLARSHIP, "conversation")
        response = engine.ask("Nếu em mất thẻ gửi xe máy thì sao?", "conversation")
        self.assertTrue(response.refused, response.answer)
        self.assertEqual(response.references, [])


if __name__ == "__main__":
    unittest.main()
