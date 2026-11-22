"""Saved presentation is a snapshot, not a fresh retrieval or a context source."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import httpx

from core import engine as engine_module
from core.corpus import build_corpus
from core.engine import HocVuEngine
from core.searcher import HybridSearcher
from core.session import SessionStore
from core.settings import AppConfig
from core.splitter import split_regulation
from server import app as server


def make_engine(root):
    config = AppConfig(semantic_enabled=False)
    searcher = HybridSearcher(config)
    searcher.build([
        chunk for regulation in build_corpus(config.seed)
        for chunk in split_regulation(regulation, config.max_chunk_chars, config.overlap_sents)
    ])
    with patch.multiple(
        engine_module, SESSION_DB=root / "sessions.db", DOCS=root / "docs",
    ):
        return HocVuEngine(config, searcher)


class HistoryMetadataTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.engine = make_engine(self.root)

    def grounded_turn(self):
        response = self.engine.ask("Điều kiện bảo lưu?", "conversation")
        self.assertFalse(response.refused, response.answer)
        self.assertTrue(response.references)
        return response.to_dict()

    def test_full_presentation_round_trips_after_database_restart(self):
        live = self.grounded_turn()
        store = SessionStore(self.root / "sessions.db")
        restored = store.get_history("conversation", 8)[0]
        for key in ("answer", "intent", "refused", "refusal_reason", "references", "card", "confidence"):
            self.assertEqual(restored[key], live[key], key)
        self.assertIs(restored["refused"], False)
        self.assertNotIn("references_json", restored)
        self.assertNotIn("card_json", restored)

    def test_saved_sources_do_not_depend_on_the_current_index(self):
        live = self.grounded_turn()
        self.engine.searcher.chunks.clear()
        restored = self.engine.history("conversation")[0]
        self.assertEqual(restored["references"], live["references"])
        self.assertEqual(restored["card"], live["card"])
        self.assertTrue(restored["references"][0]["excerpt"])

    def test_greetings_and_refusals_still_cannot_poison_persistent_context(self):
        self.grounded_turn()
        self.assertEqual(self.engine.ask("Xin chào", "conversation").intent, "greeting")
        self.assertTrue(self.engine.ask("Tự sát", "conversation").refused)
        self.assertTrue(self.engine.ask("Giá vàng hôm nay?", "conversation").refused)
        # The transcript keeps every exchange; only the grounded one is context.
        history = self.engine.history("conversation")
        self.assertEqual(
            [(turn["question"], turn["refused"]) for turn in history],
            [("Điều kiện bảo lưu?", False), ("Xin chào", False), ("Tự sát", True), ("Giá vàng hôm nay?", True)],
        )
        for turn in history[1:]:
            self.assertEqual((turn["article_id"], turn["rid"], turn["references"]), ("", "", []))
            self.assertEqual((turn["context_question"], turn["context_root"]), ("", ""))
        _, root = self.engine.session.contextualize("conversation", "Còn điều kiện nào khác?")
        self.assertEqual(root, "Điều kiện bảo lưu?")
        self.assertEqual(self.engine.session.latest_grounded_turn("conversation")["question"], "Điều kiện bảo lưu?")

    def test_refusal_survives_restart_with_its_reason_and_suggestions(self):
        live = self.engine.ask("Giá vàng hôm nay?", "conversation").to_dict()
        self.assertTrue(live["refused"])
        restored = SessionStore(self.root / "sessions.db").get_history("conversation", 8)[0]
        for key in ("answer", "intent", "refused", "refusal_reason", "card", "confidence"):
            self.assertEqual(restored[key], live[key], key)
        self.assertEqual(restored["references"], [])
        # A conversation of refusals alone offers no antecedent.
        self.assertEqual(self.engine.session.contextualize("conversation", "Còn điều kiện nào khác?"), ("Còn điều kiện nào khác?", ""))
        self.assertIsNone(self.engine.session.latest_grounded_turn("conversation"))
        self.assertTrue(self.engine.ask("Còn điều kiện nào khác?", "conversation").refused)

    def test_conversation_is_titled_by_its_first_real_question(self):
        from core.session import LEGACY_API_OWNER
        self.engine.ask("Xin chào", "conversation")
        listed = self.engine.session.list_conversations(LEGACY_API_OWNER)
        self.assertEqual([(row["title"], row["turn_count"]) for row in listed], [("Xin chào", 1)])
        self.engine.ask("Giá vàng hôm nay?", "conversation")
        self.grounded_turn()
        listed = self.engine.session.list_conversations(LEGACY_API_OWNER)
        self.assertEqual([(row["title"], row["turn_count"]) for row in listed], [("Giá vàng hôm nay?", 3)])

    def test_display_turn_cannot_store_a_grounded_academic_answer(self):
        store = self.engine.session
        response = {"refused": False, "card": {}, "confidence": 1.0, "refusal_reason": ""}
        self.assertIsNone(store.add_display_turn("conversation", "Điều kiện bảo lưu?", "Có", "academic_rules", response=response))
        self.assertIsNone(store.add_display_turn("conversation", "  ", "Có", "greeting", response=response))
        self.assertEqual(self.engine.history("conversation"), [])

    def test_restored_answer_keeps_its_wording_mode(self):
        live = self.grounded_turn()
        self.assertEqual(live["card"]["answer_mode"], "off")
        self.assertEqual(self.engine.history("conversation")[0]["card"]["answer_mode"], "off")

    def test_transcript_is_not_truncated_to_the_context_window(self):
        for _ in range(self.engine.config.max_history + 3):
            self.engine.ask("Giá vàng hôm nay?", "conversation")
        self.assertEqual(len(self.engine.history("conversation")), self.engine.config.max_history + 3)

    def test_explicitly_refused_rows_are_not_context_even_with_legacy_source_ids(self):
        self.grounded_turn()
        with sqlite3.connect(self.root / "sessions.db") as conn:
            conn.execute(
                """INSERT INTO turns (session_id, question, answer, intent, article_id, rid, refused)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                ("conversation", "Học phí thế nào?", "Không có căn cứ", "academic_rules", "Điều 1", "old", 1),
            )
        _, root = self.engine.session.contextualize("conversation", "Còn điều kiện nào khác?", limit=1)
        self.assertEqual(root, "Điều kiện bảo lưu?")
        self.assertIs(self.engine.history("conversation")[-1]["refused"], True)

    def test_add_turn_rejects_a_refused_response_with_nonempty_source_ids(self):
        result = self.engine.session.add_turn(
            "conversation", "Điều kiện bảo lưu?", "Không rõ", "academic_rules", "Điều 1", "old",
            response={"refused": True},
        )
        self.assertIsNone(result)
        self.assertEqual(self.engine.history("conversation"), [])

    def test_legacy_rows_remain_unknown_instead_of_fabricating_evidence(self):
        path = self.root / "legacy.db"
        with sqlite3.connect(path) as conn:
            conn.execute(
                """CREATE TABLE turns (
                    id INTEGER PRIMARY KEY, session_id TEXT, question TEXT, answer TEXT,
                    intent TEXT, article_id TEXT, rid TEXT)"""
            )
            conn.execute(
                "INSERT INTO turns VALUES (1, ?, ?, ?, ?, ?, ?)",
                ("conversation", "Điều kiện bảo lưu?", "Căn cứ cũ", "academic_rules", "Điều 5", "old"),
            )
        before = SessionStore(path).get_history("conversation", 8)[0]
        for key in ("refused", "references", "card", "confidence"):
            self.assertIsNone(before[key], key)
        self.assertEqual(before["answer"], "Căn cứ cũ")
        self.assertEqual(SessionStore(path).get_history("conversation", 8)[0], before)

    def test_corrupt_metadata_does_not_erase_the_original_transcript(self):
        self.grounded_turn()
        with sqlite3.connect(self.root / "sessions.db") as conn:
            conn.execute("UPDATE turns SET references_json = ?, card_json = ?", ("{broken", "[]"))
        restored = self.engine.history("conversation")[0]
        self.assertIsNone(restored["references"])
        self.assertIsNone(restored["card"])
        self.assertTrue(restored["answer"])

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed for UI regression tests")
    def test_actual_saved_response_renders_in_the_actual_ui(self):
        self.grounded_turn()
        fixture = self.root / "history.json"
        fixture.write_text(json.dumps(self.engine.history("conversation"), ensure_ascii=False), encoding="utf-8")
        project = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            ["node", "--test", str(project / "tests" / "test_ui_history.cjs")],
            cwd=project, env={**os.environ, "HV_HISTORY_FIXTURE": str(fixture)},
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class HistoryApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_history_endpoint_returns_the_original_response_state_and_isolates_sessions(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = await asyncio.to_thread(make_engine, Path(directory))
            live = (await asyncio.to_thread(engine.ask, "Điều kiện bảo lưu?", "conversation")).to_dict()
            self.assertFalse(live["refused"])
            # Legacy histories require explicit server-token authority, rather
            # than a shared browser login or merely knowing the session ID.
            from core.session import LEGACY_API_OWNER
            engine.authorize_session("conversation", LEGACY_API_OWNER, create=True)
            with (
                patch.object(server, "get_engine", return_value=engine),
                patch.object(server.config, "api_token", "metadata-test-token"),
                patch.object(server, "requires_api_token", False),
                patch.object(server, "browser_auth_enabled", False),
            ):
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=server.app), base_url="http://test",
                ) as client:
                    response = await client.get("/api/history", params={"session_id": "conversation"},
                                                headers={"X-HocVu-Token": "metadata-test-token"})
                    other = await client.get("/api/history", params={"session_id": "other"},
                                             headers={"X-HocVu-Token": "metadata-test-token"})
            self.assertEqual(response.status_code, 200)
            restored = response.json()[0]
            for key in ("refused", "references", "card", "confidence"):
                self.assertEqual(restored[key], live[key], key)
            self.assertEqual(other.json(), [])
