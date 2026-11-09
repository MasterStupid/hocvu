"""Persisted context must survive restarts and safely ignore legacy noise."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import tempfile
import unittest

from core.session import SessionStore


class SessionStoreTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "sessions.db"

    def legacy_database(self):
        with sqlite3.connect(self.path) as conn:
            conn.execute("""
                CREATE TABLE turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL, question TEXT NOT NULL,
                    answer TEXT NOT NULL, intent TEXT, article_id TEXT, rid TEXT
                )
            """)
            conn.execute(
                "INSERT INTO turns (session_id, question, answer, intent, article_id, rid) VALUES (?, ?, ?, ?, ?, ?)",
                ("conversation", "Điều kiện bảo lưu?", "Căn cứ bảo lưu", "academic_rules", "Điều 5", "source"),
            )

    def test_additive_migration_preserves_existing_transcript(self):
        self.legacy_database()
        store = SessionStore(self.path)
        before = store.get_history("conversation", 8)
        self.assertEqual(len(before), 1)
        self.assertEqual(before[0]["question"], "Điều kiện bảo lưu?")
        self.assertEqual(before[0]["context_question"], "")
        self.assertEqual(before[0]["context_root"], "")
        SessionStore(self.path)  # Idempotent migration.
        self.assertEqual(store.get_history("conversation", 8), before)
        expanded, root = store.contextualize("conversation", "Thế còn thời gian tối đa?")
        self.assertEqual(root, "Điều kiện bảo lưu?")
        self.assertIn(root, expanded)

    def test_concurrent_initialization_serializes_the_migration(self):
        self.legacy_database()
        with ThreadPoolExecutor(max_workers=4) as executor:
            stores = list(executor.map(lambda _: SessionStore(self.path), range(8)))
        self.assertTrue(all(len(store.get_history("conversation", 8)) == 1 for store in stores))

    def test_legacy_noise_does_not_hide_a_grounded_turn_outside_display_limit(self):
        self.legacy_database()
        with sqlite3.connect(self.path) as conn:
            for _ in range(12):
                for question, intent in (
                    ("Xin chào", "greeting"), ("Tự sát", "unsafe"),
                    ("Wifi ở ký túc xá thế nào?", "academic_rules"),
                ):
                    conn.execute(
                        "INSERT INTO turns (session_id, question, answer, intent, article_id, rid) VALUES (?, ?, ?, ?, ?, ?)",
                        ("conversation", question, "Không có căn cứ", intent, "", ""),
                    )
        store = SessionStore(self.path)
        expanded, root = store.contextualize("conversation", "Còn điều kiện nào khác?", limit=2)
        self.assertEqual(root, "Điều kiện bảo lưu?")
        self.assertNotIn("Xin chào", expanded)
        self.assertNotIn("Wifi", expanded)
        self.assertNotIn("Tự sát", expanded)
        # No destructive cleanup of the original transcript.
        self.assertEqual(len(store.get_history("conversation", 100)), 37)

    def test_legacy_raw_follow_up_recovers_its_earlier_root(self):
        self.legacy_database()
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "INSERT INTO turns (session_id, question, answer, intent, article_id, rid) VALUES (?, ?, ?, ?, ?, ?)",
                ("conversation", "Còn điều kiện nào khác?", "Quy định bảo lưu", "academic_rules", "Điều 5", "source"),
            )
        expanded, root = SessionStore(self.path).contextualize("conversation", "Thế còn thời gian tối đa?")
        self.assertEqual(root, "Điều kiện bảo lưu?")
        self.assertIn("bảo lưu", expanded)
        self.assertIn("thời gian tối đa", expanded)

    def test_only_a_grounded_academic_turn_is_saved(self):
        store = SessionStore(self.path)
        for question, intent, article, rid in (
            ("Xin chào", "greeting", "", ""),
            ("Xin chào", "academic_rules", "Điều 5", "source"),
            ("Tự sát", "unsafe", "", ""),
            ("Tự sát", "academic_rules", "Điều 5", "source"),
            ("Wifi thế nào?", "academic_rules", "", ""),
            ("", "academic_rules", "Điều 5", "source"),
        ):
            with self.subTest(question=question, intent=intent):
                self.assertIsNone(store.add_turn("conversation", question, "Không có căn cứ", intent, article, rid))
        self.assertEqual(store.get_history("conversation", 8), [])
        self.assertIsNotNone(store.add_turn(
            "conversation", "Điều kiện bảo lưu?", "Có căn cứ", "academic_rules", "Điều 5", "source",
        ))
        self.assertEqual(len(store.get_history("conversation", 8)), 1)

    def test_context_cannot_cross_session_boundaries(self):
        store = SessionStore(self.path)
        store.add_turn("one", "Điều kiện bảo lưu?", "Có căn cứ", "academic_rules", "Điều 5", "source")
        question = "Thế còn thời gian tối đa?"
        for session_id in ("two", "' OR 1=1 --"):
            self.assertEqual(store.contextualize(session_id, question), (question, ""))

    def test_context_root_survives_a_one_turn_history_window_and_restart(self):
        store = SessionStore(self.path)
        root = "Điều kiện bảo lưu?"
        store.add_turn("conversation", root, "Có căn cứ", "academic_rules", "Điều 5", "source")
        for _ in range(12):
            question = "Còn điều kiện nào khác?"
            expanded, actual_root = store.contextualize("conversation", question, limit=1)
            self.assertEqual(actual_root, root)
            self.assertEqual(expanded, f"{root} | {question}")
            store.add_turn(
                "conversation", question, "Có căn cứ", "academic_rules", "Điều 5", "source",
                context_question=expanded, context_root=actual_root,
            )
            store = SessionStore(self.path)

    def test_standalone_topics_do_not_inherit_prior_context(self):
        store = SessionStore(self.path)
        store.add_turn("conversation", "Điều kiện bảo lưu?", "Có căn cứ", "academic_rules", "Điều 5", "source")
        for question in ("Thế còn học phí?", "Thế còn thời gian thực tập?", "Wifi thế nào?"):
            self.assertEqual(store.contextualize("conversation", question), (question, ""))

    def test_unresolved_legacy_ellipsis_is_not_an_antecedent_by_itself(self):
        store = SessionStore(self.path)
        store.add_turn(
            "conversation", "Còn điều kiện nào khác?", "Căn cứ cũ", "academic_rules", "Điều 1", "source",
        )
        question = "Thế còn thời gian tối đa?"
        self.assertEqual(store.contextualize("conversation", question), (question, ""))
