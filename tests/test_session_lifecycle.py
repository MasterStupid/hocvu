"""Deleted IDs stay closed across overlapping requests and independent stores."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import sqlite3
import sys
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
from core.session import SessionClosedError, SessionStore
from core.settings import AppConfig
from core.splitter import split_regulation
from server import app as server


def add_turn(store, session_id):
    return store.add_turn(
        session_id, "Điều kiện bảo lưu?", "Căn cứ bảo lưu",
        "academic_rules", "Điều 5", "source",
    )


class SessionLifecycleStoreTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "sessions.db"
        self.store = SessionStore(self.path)

    def test_closed_ids_survive_new_store_and_new_process_and_are_never_reused(self):
        for session_id in ("legacy.2024", "hội thoại 2024", " ", "%", "' OR 1=1 --"):
            add_turn(self.store, session_id)
            self.assertEqual(self.store.delete_history(session_id), 1)
            restarted = SessionStore(self.path)
            self.assertTrue(restarted.is_closed(session_id))
            with self.assertRaises(SessionClosedError):
                add_turn(restarted, session_id)
            self.assertEqual(restarted.delete_history(session_id), 0)
            self.assertEqual(restarted.get_history(session_id, 100), [])
        result = subprocess.run(
            [sys.executable, "-c", """
import sys
from pathlib import Path
from core.session import SessionStore, SessionClosedError
store = SessionStore(Path(sys.argv[1]))
try:
    store.add_turn("hội thoại 2024", "Điều kiện bảo lưu?", "Căn cứ", "academic_rules", "Điều 5", "source")
except SessionClosedError:
    sys.exit(0)
sys.exit(1)
""", str(self.path)], capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNotNone(add_turn(self.store, "fresh"))
        self.assertFalse(self.store.is_closed("fresh"))
        self.assertEqual(self.store.delete_history("never-saved"), 0)
        with self.assertRaises(SessionClosedError):
            add_turn(self.store, "never-saved")

    def test_failed_deletion_rolls_back_the_tombstone_as_well_as_the_turns(self):
        add_turn(self.store, "selected")
        before = self.store.get_history("selected", 100)
        connect = sqlite3.connect

        def failing_connect(*args, **kwargs):
            conn = connect(*args, **kwargs)
            def authorize(action, table, *rest):
                if action == sqlite3.SQLITE_DELETE and table == "turns":
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK
            conn.set_authorizer(authorize)
            return conn

        with patch("core.session.sqlite3.connect", side_effect=failing_connect):
            with self.assertRaises(sqlite3.DatabaseError):
                self.store.delete_history("selected")
        self.assertFalse(self.store.is_closed("selected"))
        self.assertEqual(self.store.get_history("selected", 100), before)
        self.assertIsNotNone(add_turn(self.store, "selected"))

    def test_writer_check_and_insert_are_atomic_with_deletion(self):
        other = SessionStore(self.path)
        entered, release, deleting_started = threading.Event(), threading.Event(), threading.Event()
        original = self.store._is_closed

        def pause(conn, session_id):
            closed = original(conn, session_id)
            entered.set()
            if not release.wait(5):
                raise AssertionError("Test did not release writer")
            return closed

        def delete():
            deleting_started.set()
            return other.delete_history("selected")

        with ThreadPoolExecutor(max_workers=2) as pool, patch.object(self.store, "_is_closed", side_effect=pause):
            writing = pool.submit(add_turn, self.store, "selected")
            try:
                self.assertTrue(entered.wait(2))
                deleting = pool.submit(delete)
                self.assertTrue(deleting_started.wait(2))
                self.assertFalse(deleting.done(), "DELETE must wait for the atomic writer")
            finally:
                release.set()
            self.assertIsNotNone(writing.result(3))
            self.assertEqual(deleting.result(3), 1)
        self.assertEqual(other.get_history("selected", 100), [])
        self.assertTrue(other.is_closed("selected"))

    def test_listing_keeps_one_snapshot_during_deletion_in_delete_and_wal_modes(self):
        row_factory = sqlite3.Row
        for mode in ("DELETE", "WAL"):
            with self.subTest(journal_mode=mode):
                path = self.path.with_name(f"sessions-{mode}.db")
                store = SessionStore(path)
                other = SessionStore(path)
                # Initialization now deliberately selects WAL. Set the alternate
                # test mode after both stores exist to keep testing both snapshots.
                with sqlite3.connect(path) as conn:
                    self.assertEqual(conn.execute(f"PRAGMA journal_mode={mode}").fetchone()[0], mode.lower())
                for session_id in ("selected", "survivor"):
                    store.authorize(session_id, "a", create=True)
                    add_turn(store, session_id)
                add_turn(store, "selected")
                before = store.list_conversations("a")
                entered, release, deleting_started = threading.Event(), threading.Event(), threading.Event()

                def pause(cursor, values):
                    row = row_factory(cursor, values)
                    if not entered.is_set():
                        entered.set()
                        if not release.wait(5):
                            raise AssertionError("Test did not release conversation reader")
                    return row

                def delete():
                    deleting_started.set()
                    return other.delete_history("selected")

                with ThreadPoolExecutor(max_workers=2) as pool, patch(
                    "core.session.sqlite3.Row", side_effect=pause,
                ):
                    reading = pool.submit(store.list_conversations, "a")
                    try:
                        self.assertTrue(entered.wait(2))
                        deleting = pool.submit(delete)
                        self.assertTrue(deleting_started.wait(2))
                        if mode == "WAL":
                            # A reader must not hold a writer lock; WAL deletion
                            # commits even while this old snapshot is paused.
                            self.assertEqual(deleting.result(2), 2)
                        else:
                            self.assertFalse(deleting.done(), "DELETE commit must wait for the reader")
                    finally:
                        release.set()
                    self.assertEqual(reading.result(3), before)
                    self.assertEqual(deleting.result(3), 2)
                self.assertEqual(
                    [row["session_id"] for row in store.list_conversations("a")], ["survivor"],
                )
                self.assertTrue(other.is_closed("selected"))
                with self.assertRaises(SessionClosedError):
                    add_turn(other, "selected")


class SessionLifecycleApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

        def make_engine():
            config = AppConfig(semantic_enabled=False)
            searcher = HybridSearcher(config)
            searcher.build([
                chunk for regulation in build_corpus(config.seed)
                for chunk in split_regulation(regulation, config.max_chunk_chars, config.overlap_sents)
            ])
            with patch.multiple(
                engine_module, SESSION_DB=self.root / "sessions.db",
                DOCS=self.root / "docs",
            ):
                return HocVuEngine(config, searcher)

        self.engine = await asyncio.to_thread(make_engine)
        self.other_store = SessionStore(self.engine.session.db_path)
        for item in (
            patch.object(server, "get_engine", return_value=self.engine),
            patch.object(server, "request_limiter", server.SlidingWindowLimiter()),
            patch.object(server.config, "api_token", "synthetic-test-token"),
            patch.object(server.config, "rate_limit_per_minute", 1000),
            patch.object(server, "requires_api_token", True),
            patch.object(server, "browser_auth_enabled", True),
        ):
            item.start()
            self.addCleanup(item.stop)
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app), base_url="http://test",
            headers={"X-HocVu-Token": "synthetic-test-token", "Origin": "http://test"},
        )
        self.addAsyncCleanup(self.client.aclose)

    async def ask(self, session_id, **kwargs):
        return await self.client.post(
            "/api/ask", json={"session_id": session_id, "question": "Điều kiện bảo lưu?", **kwargs},
        )

    async def delete(self, session_id):
        return await self.client.delete("/api/history", params={"session_id": session_id})

    def assert_closed(self, response, session_id):
        self.assertEqual(response.status_code, 410, response.text)
        self.assertEqual(response.json()["code"], "session_closed")
        self.assertEqual(response.json()["session_id"], session_id)
        self.assertIn("mã phiên mới", response.json()["detail"])
        self.assertNotIn("answer", response.json())

    async def test_delete_during_generation_or_just_before_save_discards_answer_and_context(self):
        for stage in ("generation", "save"):
            with self.subTest(stage=stage):
                session_id = f"selected-{stage}"
                add_turn(self.engine.session, session_id)
                entered, release = threading.Event(), threading.Event()
                original = self.engine.session.add_turn

                def pause(*args, **kwargs):
                    entered.set()
                    if not release.wait(5):
                        raise AssertionError("Test did not release ask")
                    return "Căn cứ bảo lưu" if stage == "generation" else original(*args, **kwargs)

                target, method = (
                    (self.engine.llm, "rewrite") if stage == "generation"
                    else (self.engine.session, "add_turn")
                )
                with patch.object(target, method, side_effect=pause):
                    pending = asyncio.create_task(self.ask(session_id, use_ai=stage == "generation"))
                    try:
                        self.assertTrue(await asyncio.to_thread(entered.wait, 2))
                        deleted = await asyncio.wait_for(self.delete(session_id), 2)
                        self.assertEqual(deleted.status_code, 200, deleted.text)
                        self.assertEqual(deleted.json()["deleted_turns"], 1)
                        self.assertFalse(pending.done(), "DELETE must not wait for answer generation")
                        if stage == "generation":
                            # Another session remains usable while ask is paused.
                            quick = await asyncio.wait_for(self.ask("unrelated"), 2)
                            self.assertEqual(quick.status_code, 200, quick.text)
                            self.assertFalse(quick.json()["refused"])
                    finally:
                        release.set()
                        response = await asyncio.wait_for(pending, 3)
                self.assert_closed(response, session_id)
                self.assertEqual(self.other_store.get_history(session_id, 100), [])
                question = "Còn điều kiện nào khác?"
                self.assertEqual(self.other_store.contextualize(session_id, question), (question, ""))
                self.assert_closed(await self.ask(session_id), session_id)
        self.assertEqual(len(self.other_store.get_history("unrelated", 100)), 1)

    async def test_deletion_during_audio_generation_is_not_returned_as_an_old_answer(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def audio(*args, **kwargs):
            entered.set()
            await release.wait()
            return "/api/audio/test.mp3", None
        manager = SimpleNamespace(generate_audio_file=audio)
        with patch.object(server, "get_voice_manager", return_value=manager):
            pending = asyncio.create_task(self.ask("audio", with_audio=True))
            try:
                await asyncio.wait_for(entered.wait(), 2)
                deleted = await self.delete("audio")
                self.assertEqual(deleted.json()["deleted_turns"], 1)
            finally:
                release.set()
                response = await asyncio.wait_for(pending, 3)
        self.assert_closed(response, "audio")
        self.assertEqual(self.engine.history("audio"), [])

    async def test_no_write_answer_is_also_invalidated_when_another_client_deletes(self):
        for question in ("Xin chào", "Wifi ký túc xá thế nào?"):
            session_id = question
            entered, release = threading.Event(), threading.Event()
            classify = self.engine.classifier.classify
            def pause(text):
                entered.set()
                if not release.wait(5):
                    raise AssertionError("Test did not release classification")
                return classify(text)
            with patch.object(self.engine.classifier, "classify", side_effect=pause):
                pending = asyncio.create_task(self.ask(session_id, question=question))
                try:
                    self.assertTrue(await asyncio.to_thread(entered.wait, 2))
                    # Independent store represents a separate server process.
                    await asyncio.to_thread(self.other_store.delete_history, session_id)
                finally:
                    release.set()
                    response = await asyncio.wait_for(pending, 3)
            self.assert_closed(response, session_id)
            self.assertEqual(self.engine.history(session_id), [])

    async def test_closed_status_and_new_id_policy_preserve_existing_access_controls(self):
        add_turn(self.other_store, "legacy name")
        before = await self.client.get("/api/history/status", params={"session_id": "legacy name"})
        self.assertEqual(before.json(), {"session_id": "legacy name", "closed": False})
        await self.delete("legacy name")
        after = await self.client.get("/api/history/status", params={"session_id": "legacy name"})
        self.assertEqual(after.json(), {"session_id": "legacy name", "closed": True})
        self.assertEqual(after.headers["cache-control"], "no-store")
        with patch.object(self.engine.classifier, "classify") as classify:
            self.assert_closed(await self.ask("legacy name"), "legacy name")
            classify.assert_not_called()
        for payload in ({"session_id": "fresh"}, {}):
            response = await self.client.post(
                "/api/ask", json={"question": "Điều kiện bảo lưu?", **payload},
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertNotEqual(response.json()["session_id"], "legacy name")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app), base_url="http://test",
        ) as unauthenticated:
            for path in ("/api/history/status?session_id=legacy%20name", "/api/history?session_id=legacy%20name"):
                response = await unauthenticated.get(path)
                self.assertEqual(response.status_code, 401)
        forbidden = await self.client.post(
            "/api/ask", json={"question": "Xin chào", "session_id": "legacy name"},
            headers={"Origin": "https://attacker.test"},
        )
        self.assertEqual(forbidden.status_code, 403)
        missing = await self.client.get("/api/history/status")
        self.assertEqual(missing.status_code, 422)
        with patch.object(server.config, "rate_limit_per_minute", 1):
            limited = await self.client.get("/api/history/status", params={"session_id": "legacy name"})
            self.assertEqual(limited.status_code, 429)
