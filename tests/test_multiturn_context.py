"""Topic changes must not inherit unrelated history; references must use it."""
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.corpus import build_corpus
from core.engine import HocVuEngine
from core.scenarios import expand_retrieval_query, is_context_dependent, is_contextual_follow_up
from core.searcher import HybridSearcher
from core.settings import AppConfig
from core.splitter import split_regulation


class FollowUpRecognitionTests(unittest.TestCase):
    def test_short_independent_questions_are_not_follow_ups(self):
        for question in (
            "Đồ án là gì?", "Đồ án là gì", "Do an la gi?",
            "Học phí ra sao", "Học phí ra sao?", "Hoc phi ra sao",
            "Có học bổng không?", "Có học bổng không", "Co hoc bong khong",
            "Thi lại không?", "Điểm rèn luyện là gì?",
            "Vì sao học phí tăng?", "Còn cái đồ?", "",
        ):
            with self.subTest(question=question):
                self.assertFalse(is_contextual_follow_up(question))

    def test_real_references_ignore_punctuation_and_support_stt(self):
        for question in (
            "Còn cái đó?", "Còn cái đó", "Con cai do?",
            "CÒN CÁI ĐÓ?!", "Còn, cái đó?", "Điều đó là gì?",
            "Còn điều kiện nào khác?", "Con dieu kien nao khac",
            "Nói rõ hơn.", "Cụ thể hơn?", "Còn trường hợp này?",
            "Được không?", "Tại sao?", "Vậy sao?",
        ):
            with self.subTest(question=question):
                self.assertTrue(is_contextual_follow_up(question))
                self.assertTrue(is_context_dependent(question))

    def test_discourse_prefix_can_still_have_an_independent_subject(self):
        for question in ("Thế còn học phí?", "The con hoc phi", "Vậy còn đồ án?"):
            with self.subTest(question=question):
                self.assertTrue(is_contextual_follow_up(question))
                self.assertFalse(is_context_dependent(question))

    def test_accented_phrase_boundaries_do_not_merge_different_words(self):
        for question in ("Còn cái đồ?", "Điều đổ là gì?", "Cụ thể hớn?", "Thẻ còn học phí?"):
            with self.subTest(question=question):
                self.assertFalse(is_contextual_follow_up(question))


class MultiturnContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = AppConfig(semantic_enabled=False)
        cls.searcher = HybridSearcher(cls.config)
        cls.searcher.build([
            chunk for regulation in build_corpus()
            for chunk in split_regulation(regulation, 800, 1)
        ])

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        with patch("core.engine.SESSION_DB", Path(directory.name) / "sessions.db"):
            self.engine = HocVuEngine(self.config, self.searcher)

    def seed_history(self, session_id="conversation"):
        response = self.engine.ask("Điều kiện bảo lưu kết quả học tập là gì?", session_id)
        self.assertFalse(response.refused)
        return response

    def test_topic_changes_equal_standalone_answers_with_real_session_history(self):
        self.seed_history()
        for question in (
            "Đồ án là gì?", "Đồ án là gì", "Do an la gi?",
            "Học phí ra sao", "Học phí ra sao?", "Hoc phi ra sao",
            "Có học bổng không?", "Có học bổng không",
        ):
            with self.subTest(question=question):
                standalone = self.engine.ask(question, "standalone", use_context=False, record_session=False)
                with patch.object(self.engine.session, "contextualize", wraps=self.engine.session.contextualize) as contextualize:
                    actual = self.engine.ask(question, "conversation", record_session=False)
                self.assertFalse(standalone.refused)
                self.assertEqual(actual.refused, standalone.refused)
                self.assertEqual(actual.answer, standalone.answer)
                self.assertEqual(actual.references, standalone.references)
                self.assertEqual(actual.confidence, standalone.confidence)
                contextualize.assert_not_called()

    def test_independent_evidence_wins_even_with_a_follow_up_prefix(self):
        self.seed_history()
        question = "Thế còn học phí?"
        standalone = self.engine.ask(question, "standalone", use_context=False, record_session=False)
        with patch.object(self.engine.session, "contextualize", wraps=self.engine.session.contextualize) as contextualize:
            actual = self.engine.ask(question, "conversation", record_session=False)
        self.assertFalse(actual.refused)
        self.assertEqual(actual.answer, standalone.answer)
        self.assertEqual(actual.references, standalone.references)
        contextualize.assert_not_called()

    def test_real_follow_ups_cite_the_previous_topic_not_an_arbitrary_conditions_rule(self):
        previous = self.seed_history()
        for question in ("Còn cái đó?", "Con cai do", "Còn điều kiện nào khác?"):
            with self.subTest(question=question):
                with patch.object(self.searcher, "search", wraps=self.searcher.search) as search:
                    response = self.engine.ask(question, "conversation", record_session=False)
                self.assertFalse(response.refused)
                self.assertTrue(response.references)
                self.assertEqual(response.references[0].rid, previous.references[0].rid)
                self.assertEqual(response.references[0].aid, "Điều 5")
                queries = [call.args[0] for call in search.call_args_list]
                self.assertEqual(queries[0], expand_retrieval_query(question))
                self.assertEqual(len(queries), 2)
                self.assertIn("bảo lưu", queries[1])

    def test_reference_without_history_or_with_context_disabled_is_refused(self):
        self.seed_history()
        for session_id, use_context in (
            ("new-session", True), ("conversation", False),
        ):
            for question in ("Còn cái đó?", "Còn điều kiện nào khác?"):
                with self.subTest(session_id=session_id, use_context=use_context, question=question):
                    response = self.engine.ask(
                        question, session_id, use_context=use_context, record_session=False,
                    )
                    self.assertTrue(response.refused)
                    self.assertFalse(response.references)

    def test_unsupported_new_topic_never_borrows_the_previous_answer(self):
        self.seed_history()
        for question in (
            "Wifi ra sao", "Wifi ở ký túc xá thế nào?", "Giải bóng đá có thưởng không?",
            "Thế còn wifi?", "Vậy còn giải bóng đá?",
        ):
            with self.subTest(question=question):
                with patch.object(self.engine.session, "contextualize", wraps=self.engine.session.contextualize) as contextualize:
                    response = self.engine.ask(question, "conversation", record_session=False)
                self.assertTrue(response.refused)
                self.assertFalse(response.references)
                contextualize.assert_not_called()

    def test_refused_antecedent_cannot_make_a_generic_follow_up_grounded(self):
        self.engine.ask("Wifi ở ký túc xá thế nào?", "unsupported")
        response = self.engine.ask("Còn cái đó?", "unsupported", record_session=False)
        self.assertTrue(response.refused)
        self.assertFalse(response.references)

    def test_bm25_follow_up_floor_is_040_inclusive_with_grounded_context(self):
        self.seed_history()
        for coverage, refused in ((0.399, True), (0.40, False), (0.45, False), (0.49, False)):
            with self.subTest(coverage=coverage):
                # Keep real retrieval and specificity checks; control only the
                # confidence metric to exercise the threshold boundary.
                with patch.object(self.searcher, "lexical_coverage", return_value=coverage):
                    response = self.engine.ask("Còn cái đó?", "conversation", record_session=False)
                self.assertEqual(response.refused, refused)
                self.assertEqual(bool(response.references), not refused)
                self.assertEqual(response.confidence, coverage)
                if not refused:
                    self.assertEqual(response.references[0].aid, "Điều 5")

    def test_standalone_question_keeps_normal_bm25_floor_even_with_follow_up_prefix(self):
        self.seed_history()
        for question in ("Đồ án là gì?", "Học phí ra sao", "Thế còn học phí?"):
            with self.subTest(question=question):
                with (
                    patch.object(self.searcher, "lexical_coverage", return_value=0.45),
                    patch.object(self.engine.session, "contextualize", wraps=self.engine.session.contextualize) as contextualize,
                ):
                    response = self.engine.ask(question, "conversation", record_session=False)
                self.assertTrue(response.refused)
                self.assertFalse(response.references)
                self.assertEqual(response.confidence, 0.45)
                contextualize.assert_not_called()

    def test_follow_up_without_usable_context_does_not_get_a_grounded_answer(self):
        self.seed_history()
        for session_id, use_context in (("new-session", True), ("conversation", False)):
            with self.subTest(session_id=session_id, use_context=use_context):
                with patch.object(self.searcher, "lexical_coverage", return_value=0.45):
                    response = self.engine.ask(
                        "Còn điều kiện nào khác?", session_id,
                        use_context=use_context, record_session=False,
                    )
                self.assertTrue(response.refused)
                self.assertFalse(response.references)

    def test_semantic_follow_up_keeps_its_semantic_floor(self):
        self.seed_history()
        self.engine.config = replace(self.config, semantic_floor=0.60)
        original_search = self.searcher.search
        for score, refused in ((0.59, True), (0.60, False)):
            with self.subTest(score=score):
                def semantic_hits(*args, **kwargs):
                    return [replace(hit, score=score, vec=0.75)
                            for hit in original_search(*args, **kwargs)]
                with (
                    patch.object(self.searcher, "search", side_effect=semantic_hits),
                    patch.object(self.searcher, "lexical_coverage", return_value=0.45),
                ):
                    response = self.engine.ask("Còn cái đó?", "conversation", record_session=False)
                self.assertEqual(response.refused, refused)
                self.assertEqual(bool(response.references), not refused)
                self.assertEqual(response.confidence, score)

    def test_follow_up_does_not_raise_a_lower_configured_bm25_floor(self):
        self.seed_history()
        self.engine.config = replace(self.config, lexical_coverage_floor=0.35)
        with patch.object(self.searcher, "lexical_coverage", return_value=0.35):
            response = self.engine.ask("Còn cái đó?", "conversation", record_session=False)
        self.assertFalse(response.refused)
        self.assertTrue(response.references)
        self.assertEqual(response.confidence, 0.35)

    def test_reduced_follow_up_floor_does_not_bypass_specific_evidence(self):
        self.seed_history()
        with (
            patch.object(self.searcher, "lexical_coverage", return_value=0.45),
            patch.object(self.searcher, "has_specific_evidence", return_value=False),
        ):
            response = self.engine.ask("Còn cái đó?", "conversation", record_session=False)
        self.assertTrue(response.refused)
        self.assertFalse(response.references)
