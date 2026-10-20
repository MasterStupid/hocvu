"""Conversation discovery is scoped, not an index of everybody's session IDs."""
import asyncio
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import httpx

from core.session import LEGACY_API_OWNER, SessionAccessError, SessionStore
from server import app as server
from test_history_metadata import make_engine


def add_turn(store, session_id, question="Điều kiện bảo lưu?"):
    return store.add_turn(session_id, question, "Căn cứ gốc", "academic_rules", "Điều 5", "source")


class ConversationStoreTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "sessions.db"
        self.store = SessionStore(self.path)

    def test_scoped_list_has_first_question_all_turn_counts_and_newest_first(self):
        for session_id, owner in (("older", "a"), ("private", "b"), ("newer", "a")):
            self.store.authorize(session_id, owner, create=True)
            add_turn(self.store, session_id)
        add_turn(self.store, "older", "Còn điều kiện nào khác?")
        self.store.authorize("empty", "a", create=True)
        rows = SessionStore(self.path).list_conversations("a")
        self.assertEqual([r["session_id"] for r in rows], ["older", "newer"])
        self.assertEqual(rows[0]["title"], "Điều kiện bảo lưu?")
        self.assertEqual(rows[0]["turn_count"], 2)
        self.assertTrue(rows[0]["updated_at"].endswith("Z"))
        self.assertEqual(set(rows[0]), {"session_id", "title", "turn_count", "updated_at"})
        self.store.delete_history("older")
        self.assertEqual([r["session_id"] for r in self.store.list_conversations("a")], ["newer"])
        self.assertEqual([r["session_id"] for r in self.store.list_conversations("b")], ["private"])

    def test_legacy_schema_migration_is_additive_and_does_not_auto_assign_ownership(self):
        # Simulate a database created before owner records were introduced.
        with sqlite3.connect(self.path) as conn:
            conn.execute("DROP TABLE session_owners")
        store = SessionStore(self.path)
        add_turn(store, "hội thoại 2024")
        self.assertEqual(store.list_conversations("a"), [])
        for operation in (
            lambda: store.authorize("hội thoại 2024", "a", create=True),
            lambda: store.get_history("hội thoại 2024", 8, owner="a"),
            lambda: store.is_closed("hội thoại 2024", owner="a"),
        ):
            with self.assertRaises(SessionAccessError):
                operation()
        self.assertEqual(len(store.list_conversations(LEGACY_API_OWNER)), 1)
        self.assertEqual(len(store.get_history("hội thoại 2024", 8, owner=LEGACY_API_OWNER)), 1)

    def test_simultaneous_claims_never_reassign_a_session(self):
        def claim(owner):
            try:
                SessionStore(self.path).authorize("shared-id", owner, create=True)
                return owner
            except SessionAccessError:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            winners = list(pool.map(claim, ("a", "b")))
        self.assertEqual(sum(w is not None for w in winners), 1)
        winner = next(w for w in winners if w)
        other = "b" if winner == "a" else "a"
        add_turn(self.store, "shared-id")
        with self.assertRaises(SessionAccessError):
            self.store.get_history("shared-id", 8, owner=other)
        self.store.delete_history("shared-id")
        with self.assertRaises(SessionAccessError):
            self.store.authorize("shared-id", other, create=True)
        self.assertTrue(self.store.is_closed("shared-id", owner=winner))


class ConversationApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.engine = await asyncio.to_thread(make_engine, Path(directory.name))
        for item in (
            patch.object(server, "get_engine", return_value=self.engine),
            patch.object(server, "request_limiter", server.SlidingWindowLimiter()),
            patch.object(server.config, "api_token", "conversation-test-token"),
            patch.object(server.config, "rate_limit_per_minute", 1000),
            patch.object(server, "requires_api_token", True),
            patch.object(server, "browser_auth_enabled", True),
        ):
            item.start()
            self.addCleanup(item.stop)
        self.a, self.b = [
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=server.app), base_url="http://test",
                auth=("hocvu", "conversation-test-token"),
                headers={"X-HocVu-Owner": key * 64, "Origin": "http://test"},
            ) for key in ("a", "b")
        ]
        self.addAsyncCleanup(self.a.aclose)
        self.addAsyncCleanup(self.b.aclose)

    async def ask(self, client, session_id, question="Điều kiện bảo lưu?"):
        response = await client.post("/api/ask", json={"session_id": session_id, "question": question})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    async def test_switch_refresh_and_delete_selected_restore_exact_evidence_and_context(self):
        first = await self.ask(self.a, "hội thoại / 1?")
        second = await self.ask(self.a, "second")
        # Recreate the engine store to exercise persistence rather than memory.
        self.engine.session = SessionStore(self.engine.session.db_path)
        rows = await self.a.get("/api/conversations")
        self.assertEqual(rows.headers["cache-control"], "no-store")
        self.assertEqual([r["session_id"] for r in rows.json()], ["second", "hội thoại / 1?"])
        for session_id, live in (("hội thoại / 1?", first), ("second", second)):
            restored = await self.a.get("/api/history", params={"session_id": session_id})
            self.assertEqual(restored.status_code, 200)
            saved = restored.json()[0]
            for key in ("answer", "references", "card", "confidence", "refused"):
                self.assertEqual(saved[key], live[key], key)
        followup = await self.ask(self.a, "hội thoại / 1?", "Còn điều kiện nào khác?")
        self.assertFalse(followup["refused"])
        self.assertIn("Điều kiện bảo lưu?", self.engine.session.contextualize(
            "hội thoại / 1?", "Còn gì nữa?",
        )[0])
        deleted = await self.a.delete("/api/history", params={"session_id": "hội thoại / 1?"})
        self.assertEqual(deleted.json()["deleted_turns"], 2)
        self.assertEqual([r["session_id"] for r in (await self.a.get("/api/conversations")).json()], ["second"])
        self.assertEqual(len((await self.a.get("/api/history", params={"session_id": "second"})).json()), 1)
        closed = await self.a.post("/api/ask", json={"session_id": "hội thoại / 1?", "question": "Xin chào"})
        self.assertEqual(closed.status_code, 410)

    async def test_same_shared_password_cannot_list_read_continue_or_delete_another_browser(self):
        await self.ask(self.a, "private")
        await self.ask(self.b, "own")
        self.assertEqual([r["session_id"] for r in (await self.b.get("/api/conversations")).json()], ["own"])
        for method, path, kwargs in (
            ("GET", "/api/history", {"params": {"session_id": "private"}}),
            ("GET", "/api/history/status", {"params": {"session_id": "private"}}),
            ("POST", "/api/ask", {"json": {"session_id": "private", "question": "Điều kiện bảo lưu?"}}),
            ("DELETE", "/api/history", {"params": {"session_id": "private"}}),
        ):
            response = await self.b.request(method, path, **kwargs)
            self.assertEqual(response.status_code, 404, response.text)
            self.assertEqual(response.json()["code"], "session_unavailable")
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertNotIn("private", response.text)
        self.assertEqual(len(self.engine.history("private")), 1)
        # Even an explicit API token grants only legacy scope, not browser data.
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app), base_url="http://test",
            headers={"X-HocVu-Token": "conversation-test-token"},
        ) as service:
            self.assertEqual((await service.get("/api/conversations")).json(), [])
            denied = await service.get("/api/history", params={"session_id": "private"})
            self.assertEqual(denied.status_code, 404)

    async def test_legacy_sessions_are_never_claimed_by_browser_and_basic_alone_cannot_list(self):
        add_turn(self.engine.session, "legacy")
        self.assertEqual((await self.a.get("/api/conversations")).json(), [])
        for path in ("/api/history", "/api/history/status"):
            self.assertEqual((await self.a.get(path, params={"session_id": "legacy"})).status_code, 404)
        denied = await self.a.delete("/api/history", params={"session_id": "legacy"})
        self.assertEqual(denied.status_code, 404)
        self.assertEqual(len(self.engine.history("legacy")), 1)
        for key in ("", "short", "g" * 64, "a" * 65):
            denied = await self.a.get("/api/conversations", headers={"X-HocVu-Owner": key})
            self.assertEqual(denied.status_code, 401)
        request = self.a.build_request("GET", "/api/conversations")
        del request.headers["X-HocVu-Owner"]
        self.assertEqual((await self.a.send(request)).status_code, 401)
        # The database stores the digest, not the browser's bearer secret.
        await self.ask(self.a, "hashed")
        with sqlite3.connect(self.engine.session.db_path) as conn:
            owner = conn.execute("SELECT owner FROM session_owners WHERE session_id='hashed'").fetchone()[0]
        self.assertEqual(owner, hashlib.sha256(("a" * 64).encode()).hexdigest())

    async def test_origin_auth_rate_limit_and_empty_greeting_policy_are_preserved(self):
        await self.ask(self.a, "greeting", "Xin chào")
        self.assertEqual((await self.a.get("/api/conversations")).json(), [])
        forbidden = await self.a.delete(
            "/api/history", params={"session_id": "greeting"},
            headers={"Origin": "https://attacker.test"},
        )
        self.assertEqual(forbidden.status_code, 403)
        with patch.object(server.config, "rate_limit_per_minute", 1):
            self.assertEqual((await self.a.get("/api/conversations")).status_code, 429)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app), base_url="http://test",
        ) as anonymous:
            self.assertEqual((await anonymous.get("/api/conversations")).status_code, 401)
