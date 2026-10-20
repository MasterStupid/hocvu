"""Permanent deletion must be explicit, session-scoped and protected."""
import asyncio
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import threading
from types import SimpleNamespace
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


def seed(store):
    for session_id, count in (("selected", 12), ("selected-other", 2), ("SELECTED", 1)):
        for _ in range(count):
            store.add_turn(
                session_id, "Điều kiện bảo lưu?", "Căn cứ bảo lưu",
                "academic_rules", "Điều 5", "source",
            )


class DeleteHistoryStoreTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "sessions.db"
        self.store = SessionStore(self.path)
        seed(self.store)

    def test_deletes_all_selected_turns_not_just_display_window_and_survives_restart(self):
        others = [self.store.get_history(key, 100) for key in ("selected-other", "SELECTED")]
        self.assertEqual(self.store.delete_history("selected"), 12)
        restarted = SessionStore(self.path)
        self.assertEqual(restarted.get_history("selected", 100), [])
        question = "Còn điều kiện nào khác?"
        self.assertEqual(restarted.contextualize("selected", question), (question, ""))
        self.assertEqual(
            [restarted.get_history(key, 100) for key in ("selected-other", "SELECTED")], others,
        )
        self.assertEqual(restarted.delete_history("selected"), 0)
        self.assertEqual(restarted.delete_history("unknown"), 0)

    def test_invalid_ids_are_rejected_before_opening_sqlite(self):
        for bad in (None, "", [], {}, 1, False, ["selected"], b"selected"):
            with self.subTest(session_id=bad), patch("core.session.sqlite3.connect") as connect:
                with self.assertRaises(ValueError):
                    self.store.delete_history(bad)
                connect.assert_not_called()
        self.assertEqual(len(self.store.get_history("selected", 100)), 12)

    def test_valid_opaque_ids_use_exact_case_sensitive_equality(self):
        for key in (
            "one", "a_b-2", "x" * 256, "6b71f006-cec2-4eab-92da-4660c036dc05",
            "legacy.2024", "hội thoại 2024", " ", "\n", "*", "%",
            "' OR 1=1 --", "selected,selected-other", "../selected", "selected\n",
        ):
            self.store.add_turn(key, "Điều kiện bảo lưu?", "Có căn cứ", "academic_rules", "Điều 5", "source")
            self.assertEqual(self.store.delete_history(key), 1)
        self.assertEqual(len(self.store.get_history("selected", 100)), 12)

    def test_unknown_names_and_wildcards_do_not_delete_other_sessions(self):
        for key in ("unknown", "*", "%", "' OR 1=1 --", "selected,selected-other"):
            self.assertEqual(self.store.delete_history(key), 0)
        self.assertEqual(len(self.store.get_history("selected", 100)), 12)
        self.assertEqual(len(self.store.get_history("selected-other", 100)), 2)

    def test_engine_delegates_to_store_without_touching_other_sessions(self):
        engine = HocVuEngine.__new__(HocVuEngine)
        engine.session = self.store
        self.assertEqual(engine.delete_history("selected"), 12)
        self.assertEqual(len(self.store.get_history("selected-other", 100)), 2)


class DeleteHistoryApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = SessionStore(Path(directory.name) / "sessions.db")
        seed(self.store)
        self.engine = HocVuEngine.__new__(HocVuEngine)
        self.engine.session = self.store
        self.engine.config = SimpleNamespace(max_history=8)
        for item in (
            patch.object(server, "get_engine", return_value=self.engine),
            patch.object(server, "request_limiter", server.SlidingWindowLimiter()),
            patch.object(server.config, "api_token", "synthetic-test-token"),
            patch.object(server.config, "rate_limit_per_minute", 1000),
            patch.object(server, "requires_api_token", True),
            patch.object(server, "browser_auth_enabled", True),
            patch.object(server, "trusted_origins", frozenset()),
        ):
            item.start()
            self.addCleanup(item.stop)
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app), base_url="http://test",
        )
        self.addAsyncCleanup(self.client.aclose)
        self.headers = {"X-HocVu-Token": "synthetic-test-token", "Origin": "http://test"}

    async def delete(self, **kwargs):
        return await self.client.delete(
            "/api/history", params={"session_id": "selected"},
            **kwargs,
        )

    async def test_token_delete_is_permanent_isolated_and_idempotent_through_api(self):
        before = self.store.get_history("selected-other", 100)
        response = await self.delete(headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "status": "deleted", "session_id": "selected", "deleted_turns": 12,
        })
        history = await self.client.get(
            "/api/history", params={"session_id": "selected"}, headers=self.headers,
        )
        self.assertEqual(history.json(), [])
        self.assertEqual(self.store.get_history("selected-other", 100), before)
        self.assertEqual(len(self.store.get_history("SELECTED", 100)), 1)
        again = await self.delete(headers=self.headers)
        self.assertEqual(again.json()["deleted_turns"], 0)

    async def test_invalid_missing_array_and_duplicate_ids_never_reach_engine(self):
        cases = [
            [], [("session_id", "")], [("session_id[]", "selected")],
            [("session_id", "selected"), ("session_id", "selected-other")],
            [("session_id", "selected"), ("session_id", "selected")],
        ]
        with patch.object(server, "get_engine") as get_engine:
            for params in cases:
                with self.subTest(params=params):
                    response = await self.client.delete("/api/history", params=params, headers=self.headers)
                    self.assertEqual(response.status_code, 422, response.text)
            # A body cannot accidentally become an all-session delete.
            for body in ({}, {"session_id": None}, {"session_id": ["selected", "selected-other"]}):
                response = await self.client.request("DELETE", "/api/history", json=body, headers=self.headers)
                self.assertEqual(response.status_code, 422)
            get_engine.assert_not_called()
        self.assertEqual(len(self.store.get_history("selected", 100)), 12)

    async def test_legacy_names_can_be_saved_read_and_deleted_without_normalization(self):
        def make_engine():
            config = AppConfig(semantic_enabled=False)
            searcher = HybridSearcher(config)
            searcher.build([
                chunk for regulation in build_corpus(config.seed)
                for chunk in split_regulation(regulation, config.max_chunk_chars, config.overlap_sents)
            ])
            root = self.store.db_path.parent
            with patch.multiple(
                engine_module, SESSION_DB=self.store.db_path, DOCS=root / "docs", AUD=root / "audio",
            ):
                return HocVuEngine(config, searcher)

        engine = await asyncio.to_thread(make_engine)
        with patch.object(server, "get_engine", return_value=engine):
            for session_id in ("legacy.2024", "hội thoại 2024", "x" * 256, " padded ", " "):
                with self.subTest(session_id=session_id):
                    saved = await self.client.post(
                        "/api/ask", json={"question": "Điều kiện bảo lưu?", "session_id": session_id},
                        headers=self.headers,
                    )
                    self.assertEqual(saved.status_code, 200, saved.text)
                    self.assertFalse(saved.json()["refused"])
                    history = await self.client.get(
                        "/api/history", params={"session_id": session_id}, headers=self.headers,
                    )
                    self.assertEqual(history.status_code, 200)
                    self.assertEqual(len(history.json()), 1)
                    self.assertEqual(history.json()[0]["session_id"], session_id)
                    deleted = await self.client.delete(
                        "/api/history", params={"session_id": session_id}, headers=self.headers,
                    )
                    self.assertEqual(deleted.status_code, 200, deleted.text)
                    self.assertEqual(deleted.json()["deleted_turns"], 1)
                    self.assertEqual(deleted.json()["session_id"], session_id)
                    restored = await self.client.get(
                        "/api/history", params={"session_id": session_id}, headers=self.headers,
                    )
                    self.assertEqual(restored.json(), [])
        self.assertEqual(len(self.store.get_history("selected", 100)), 12)

    async def test_wrong_names_and_selector_like_strings_cannot_cause_bulk_deletion(self):
        for session_id in ("unknown", "*", "%", "' OR 1=1 --", '["selected","selected-other"]', "selected,selected-other"):
            with self.subTest(session_id=session_id):
                deleted = await self.client.delete(
                    "/api/history", params={"session_id": session_id}, headers=self.headers,
                )
                self.assertEqual(deleted.status_code, 200)
                self.assertEqual(deleted.json()["deleted_turns"], 0)
        self.assertEqual(len(self.store.get_history("selected", 100)), 12)
        self.assertEqual(len(self.store.get_history("selected-other", 100)), 2)

    async def test_unauthorized_requests_never_reach_engine(self):
        with patch.object(server, "get_engine") as get_engine:
            for browser_mode in (False, True):
                with patch.object(server, "browser_auth_enabled", browser_mode):
                    for headers in ({}, {"X-HocVu-Token": "wrong"}):
                        response = await self.delete(headers={**headers, "Origin": "http://test"})
                        self.assertEqual(response.status_code, 401)
            get_engine.assert_not_called()
        self.assertEqual(len(self.store.get_history("selected", 100)), 12)

    async def test_browser_auth_requires_same_origin_even_with_valid_credentials(self):
        with patch.object(server, "get_engine") as get_engine:
            for headers in ({}, {"Origin": "null"}, {"Origin": "https://attacker.test"},
                            {"Origin": "http://test", "Sec-Fetch-Site": "cross-site"}):
                response = await self.delete(headers=headers, auth=("hocvu", "synthetic-test-token"))
                self.assertEqual(response.status_code, 403)
            get_engine.assert_not_called()
        # A shared browser password alone no longer authorizes legacy histories.
        missing_owner = await self.delete(headers={"Origin": "http://test"}, auth=("hocvu", "synthetic-test-token"))
        self.assertEqual(missing_owner.status_code, 401)
        allowed = await self.client.delete(
            "/api/history", params={"session_id": "new-browser-session"},
            headers={"Origin": "http://test", "X-HocVu-Owner": "a" * 64},
            auth=("hocvu", "synthetic-test-token"),
        )
        self.assertEqual(allowed.status_code, 200)

    async def test_token_cannot_bypass_cross_site_protection(self):
        with patch.object(server, "get_engine") as get_engine:
            response = await self.delete(headers={**self.headers, "Origin": "https://attacker.test"})
            self.assertEqual(response.status_code, 403)
            get_engine.assert_not_called()

    async def test_rate_limit_prevents_delete_without_touching_data(self):
        with patch.object(server.config, "rate_limit_per_minute", 1):
            first = await self.client.get("/api/history", params={"session_id": "selected"}, headers=self.headers)
            self.assertEqual(first.status_code, 200)
            with patch.object(server, "get_engine") as get_engine:
                response = await self.delete(headers=self.headers)
                self.assertEqual(response.status_code, 429)
                self.assertIn("retry-after", response.headers)
                get_engine.assert_not_called()
        self.assertEqual(len(self.store.get_history("selected", 100)), 12)

    async def test_sqlite_lock_and_lazy_initialization_do_not_block_event_loop(self):
        entered, release = threading.Event(), threading.Event()
        loop_thread = threading.get_ident()
        engine = self.engine
        def initialize():
            self.assertNotEqual(threading.get_ident(), loop_thread)
            entered.set()
            if not release.wait(5):
                raise AssertionError("Test did not release engine initialization")
            return engine
        # The real DELETE waits on a real SQLite writer, not on the event loop.
        conn = sqlite3.connect(self.store.db_path)
        self.addCleanup(conn.close)
        conn.execute("BEGIN IMMEDIATE")
        with patch.object(server, "get_engine", side_effect=initialize):
            pending = asyncio.create_task(self.delete(headers=self.headers))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 2))
                asset = await asyncio.wait_for(
                    self.client.get("/main.js", auth=("hocvu", "synthetic-test-token")), 2,
                )
                self.assertEqual(asset.status_code, 200)
                release.set()
                await asyncio.sleep(.05)
                self.assertFalse(pending.done())
                asset = await asyncio.wait_for(
                    self.client.get("/main.js", auth=("hocvu", "synthetic-test-token")), 2,
                )
                self.assertEqual(asset.status_code, 200)
            finally:
                conn.rollback()
                release.set()
                response = await asyncio.wait_for(pending, 3)
        self.assertEqual(response.status_code, 200)


class DeleteHistoryUiTests(unittest.TestCase):
    def test_real_ui_delete_flow(self):
        result = subprocess.run(
            ["node", "--test", "tests/test_ui_history.cjs"],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
