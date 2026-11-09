import asyncio
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import AsyncMock, Mock, patch

import anyio
from fastapi import HTTPException
import httpx

from core.documents import DocumentError, DocumentRepository
from server import app as server


class ServerResponsivenessTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        for item in (
            patch.object(server, "requires_api_token", False),
            patch.object(server, "browser_auth_enabled", False),
            patch.object(server, "request_limiter", server.SlidingWindowLimiter()),
            patch.object(server, "_document_write_lock", anyio.Lock()),
        ):
            item.start()
            self.addCleanup(item.stop)
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app), base_url="http://test",
            headers={"Origin": "http://test", "X-HocVu-Owner": "a" * 64},
        )
        self.addAsyncCleanup(self.client.aclose)
        self.loop_thread = threading.get_ident()
        self.engine = SimpleNamespace(
            list_documents=lambda: [], searcher=SimpleNamespace(provider="bm25", semantic_error=""),
            ask=lambda **kwargs: SimpleNamespace(to_dict=lambda: {"answer": "Đã trả lời."}),
            authorize_session=lambda *args, **kwargs: None,
        )

    async def upload_directly(self, file):
        return await server.upload_document(
            file=file, ocr="", order="", decision_number="", article_clause="", document_date="",
        )

    async def test_oversized_upload_reads_only_limit_plus_one_and_never_loads_engine(self):
        file = SimpleNamespace(filename="huge.pdf", read=AsyncMock(return_value=b"x" * 65))
        with patch.object(DocumentRepository, "max_bytes", 64), patch.object(server, "get_engine") as get_engine:
            with self.assertRaises(HTTPException) as caught:
                await self.upload_directly(file)
        self.assertEqual(caught.exception.status_code, 400)
        file.read.assert_awaited_once_with(65)
        get_engine.assert_not_called()

    async def test_exact_limit_is_accepted_and_engine_runs_off_loop(self):
        file = SimpleNamespace(filename="limit.pdf", read=AsyncMock(return_value=b"x" * 64))
        def add_document(*args, **kwargs):
            self.assertNotEqual(threading.get_ident(), self.loop_thread)
            return {"id": "accepted"}
        self.engine.add_document = Mock(side_effect=add_document)
        with patch.object(DocumentRepository, "max_bytes", 64), patch.object(server, "get_engine", return_value=self.engine):
            result = await self.upload_directly(file)
        self.assertEqual(result["id"], "accepted")
        file.read.assert_awaited_once_with(65)
        self.engine.add_document.assert_called_once_with(
            "limit.pdf", b"x" * 64, use_ocr=False,
            metadata={"order": "", "decision_number": "", "article_clause": "", "document_date": ""},
        )

    async def test_http_oversized_file_is_rejected_before_engine_access(self):
        with patch.object(DocumentRepository, "max_bytes", 64), patch.object(server, "get_engine") as get_engine:
            response = await self.client.post(
                "/api/documents/upload", files={"file": ("huge.pdf", b"x" * 65)},
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("25 MB", response.json()["detail"])
        get_engine.assert_not_called()

    async def test_heavy_routes_allow_health_and_another_question_to_finish_while_blocked(self):
        cases = [
            ("ask", "POST", "/api/ask", {"json": {"question": "slow"}}, 200),
            ("add_document", "POST", "/api/documents/upload", {"files": {"file": ("a.pdf", b"%PDF-test")}}, 201),
            ("remove_document", "DELETE", "/api/documents/a", {}, 200),
            ("rebuild_index", "POST", "/api/documents/reindex", {}, 200),
            ("update_document_date", "PATCH", "/api/documents/a/date", {"json": {"document_date": "2026-10-01"}}, 200),
            ("document_text", "GET", "/api/documents/a/text", {}, 200),
        ]
        for name, method, url, kwargs, expected in cases:
            with self.subTest(operation=name):
                entered, release = threading.Event(), threading.Event()
                def blocking(*args, **call_kwargs):
                    if name == "ask" and call_kwargs.get("question") != "slow":
                        return SimpleNamespace(to_dict=lambda: {"answer": "Quick response"})
                    self.assertNotEqual(threading.get_ident(), self.loop_thread)
                    entered.set()
                    if not release.wait(5):
                        raise AssertionError("Test did not release blocked operation")
                    if name == "ask":
                        return SimpleNamespace(to_dict=lambda: {"answer": "Slow response"})
                    return {"id": "a", "status": "ok"}
                previous = getattr(self.engine, name, None)
                setattr(self.engine, name, blocking)
                with patch.object(server, "get_engine", return_value=self.engine):
                    pending = asyncio.create_task(self.client.request(method, url, **kwargs))
                    try:
                        self.assertTrue(await asyncio.to_thread(entered.wait, 2))
                        self.assertFalse(pending.done())
                        health = await asyncio.wait_for(self.client.get("/api/health"), 2)
                        quick = await asyncio.wait_for(
                            self.client.post("/api/ask", json={"question": "quick"}), 2,
                        )
                        self.assertEqual(health.status_code, 200)
                        self.assertEqual(quick.status_code, 200)
                        self.assertFalse(pending.done())
                    finally:
                        release.set()
                        result = await asyncio.wait_for(pending, 3)
                        setattr(self.engine, name, previous)
                self.assertEqual(result.status_code, expected, result.text)

    async def test_lazy_engine_initialization_does_not_block_static_assets(self):
        entered, release = threading.Event(), threading.Event()
        def factory():
            self.assertNotEqual(threading.get_ident(), self.loop_thread)
            entered.set()
            if not release.wait(5):
                raise AssertionError("Test did not release lazy initialization")
            return self.engine
        with patch.object(server, "get_engine", side_effect=factory):
            pending = asyncio.create_task(self.client.post("/api/ask", json={"question": "quick"}))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 2))
                asset = await asyncio.wait_for(self.client.get("/styles.css"), 2)
                self.assertEqual(asset.status_code, 200)
                self.assertFalse(pending.done())
            finally:
                release.set()
                result = await asyncio.wait_for(pending, 3)
        self.assertEqual(result.status_code, 200)

    async def test_mutations_are_serialized_without_blocking_readers_or_reading_queued_uploads(self):
        entered, release = threading.Event(), threading.Event()
        calls = []
        def first(*args, **kwargs):
            calls.append("first")
            entered.set()
            if not release.wait(5):
                raise AssertionError("Test did not release first writer")
            return {"id": "first"}
        self.engine.add_document = first
        self.engine.rebuild_index = lambda: calls.append("reindex") or {"status": "ok"}
        queued_file = SimpleNamespace(filename="queued.pdf", read=AsyncMock(return_value=b"%PDF-queued"))
        with patch.object(server, "get_engine", return_value=self.engine):
            pending = asyncio.create_task(self.client.post(
                "/api/documents/upload", files={"file": ("first.pdf", b"%PDF-first")},
            ))
            self.assertTrue(await asyncio.to_thread(entered.wait, 2))
            queued = asyncio.create_task(self.upload_directly(queued_file))
            reindex = asyncio.create_task(self.client.post("/api/documents/reindex"))
            try:
                health = await asyncio.wait_for(self.client.get("/api/health"), 2)
                self.assertEqual(health.status_code, 200)
                self.assertEqual(calls, ["first"])
                queued_file.read.assert_not_awaited()
                self.assertFalse(reindex.done())
                # The next writer is no longer blocked once the first finishes.
                self.engine.add_document = lambda *args, **kwargs: {"id": "queued"}
            finally:
                release.set()
                responses = await asyncio.wait_for(asyncio.gather(pending, queued, reindex), 3)
        self.assertEqual(responses[0].status_code, 201)
        self.assertEqual(responses[1]["id"], "queued")
        self.assertEqual(responses[2].status_code, 200)
        queued_file.read.assert_awaited_once_with(DocumentRepository.max_bytes + 1)

    async def test_failed_mutation_releases_the_writer_lock(self):
        self.engine.add_document = Mock(side_effect=DocumentError("Tệp không hợp lệ."))
        self.engine.rebuild_index = lambda: {"status": "ok"}
        with patch.object(server, "get_engine", return_value=self.engine):
            failed = await self.client.post("/api/documents/upload", files={"file": ("a.pdf", b"bad")})
            repaired = await asyncio.wait_for(self.client.post("/api/documents/reindex"), 2)
        self.assertEqual(failed.status_code, 400)
        self.assertEqual(repaired.status_code, 200)
