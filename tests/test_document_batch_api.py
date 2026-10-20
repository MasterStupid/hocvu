"""Bounded batch admission, cancellation and API transaction regressions."""
import asyncio
from contextlib import asynccontextmanager
import io
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import anyio
import httpx
from fastapi import HTTPException
from starlette.datastructures import FormData, UploadFile

from core.documents import DocumentError, DocumentNotFoundError, DocumentRepository
from core.engine import HocVuEngine, build_index
from core.settings import AppConfig
from server import app as server


class DocumentBatchAPITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        for context in (
            patch.object(server, "requires_api_token", False),
            patch.object(server, "browser_auth_enabled", False),
            patch.object(server, "request_limiter", server.SlidingWindowLimiter()),
            patch.object(server, "_document_write_lock", anyio.Lock()),
        ):
            self.enterContext(context)
        self.engine = SimpleNamespace(
            add_documents=Mock(return_value={"items": [{"id": "a"}, {"id": "b"}]}),
            remove_documents=Mock(return_value={"deleted": ["a", "b"], "cleanup_pending": []}),
            list_documents=lambda: [],
            searcher=SimpleNamespace(provider="bm25", semantic_error=""),
        )
        self.get_engine = self.enterContext(patch.object(server, "get_engine", side_effect=lambda: self.engine))
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app), base_url="http://test",
            headers={"Origin": "http://test"},
        )
        self.addAsyncCleanup(self.client.aclose)

    def files(self, count=2, content=b"%PDF-test"):
        return [("files", (f"{i}.pdf", content + str(i).encode())) for i in range(count)]

    async def upload(self, metadata=None, **kwargs):
        return await self.client.post(
            "/api/documents/upload-batch", files=self.files(),
            data={"metadata": json.dumps(metadata if metadata is not None else [{}, {}])}, **kwargs,
        )

    def spooled_request(self, contents, metadata=None):
        files = [UploadFile(io.BytesIO(content), filename=f"{i}.pdf") for i, content in enumerate(contents)]
        for file in files:
            file.read = AsyncMock(wraps=file.read)
        form = FormData([
            *[("files", file) for file in files],
            ("metadata", json.dumps(metadata if metadata is not None else [{} for _ in files])),
        ])
        @asynccontextmanager
        async def parsed_form(**kwargs):
            try:
                yield form
            finally:
                await form.close()
        return SimpleNamespace(form=Mock(side_effect=parsed_form)), files

    async def test_batch_metadata_is_paired_and_engine_runs_once_off_event_loop(self):
        loop_thread = threading.get_ident()
        def add(uploads):
            self.assertNotEqual(threading.get_ident(), loop_thread)
            return {"items": [{"id": str(i)} for i in range(len(uploads))]}
        self.engine.add_documents.side_effect = add
        response = await self.upload([
            {"ocr": True, "order": "4", "article_clause": "Điều 5", "document_date": "2020-01-01"},
            {"ocr": False, "decision_number": "12/QĐ"},
        ])
        self.assertEqual(response.status_code, 201, response.text)
        self.engine.add_documents.assert_called_once()
        uploads = self.engine.add_documents.call_args.args[0]
        self.assertEqual([upload["filename"] for upload in uploads], ["0.pdf", "1.pdf"])
        self.assertEqual(uploads[0]["content"], b"%PDF-test0")
        self.assertTrue(uploads[0]["use_ocr"])
        self.assertEqual(uploads[0]["metadata"]["article_clause"], "Điều 5")
        self.assertEqual(uploads[1]["metadata"]["decision_number"], "12/QĐ")

    async def test_invalid_metadata_is_rejected_before_reading_buffers_or_loading_engine(self):
        for raw in ("{", "{}", "[]", '[{}, {}, {}]', '[{"ocr":"false"},{}]', '[{"order":3},{}]', '[{"extra":"x"},{}]'):
            with self.subTest(raw=raw), patch.object(UploadFile, "read", new_callable=AsyncMock) as read:
                response = await self.client.post(
                    "/api/documents/upload-batch", files=self.files(), data={"metadata": raw},
                )
                self.assertEqual(response.status_code, 400, response.text)
                read.assert_not_awaited()
        self.get_engine.assert_not_called()

    async def test_multipart_file_count_is_bounded_before_engine_access(self):
        response = await self.client.post(
            "/api/documents/upload-batch", files=self.files(21),
            data={"metadata": json.dumps([{}] * 21)},
        )
        self.assertEqual(response.status_code, 400, response.text)
        self.get_engine.assert_not_called()
        # Unexpected file fields also count against the parser's limit.
        response = await self.client.post(
            "/api/documents/upload-batch", files=[("extra", ("extra.pdf", b"x"))],
            data={"metadata": "[]"},
        )
        self.assertEqual(response.status_code, 400)

    async def test_batch_reads_stop_at_per_file_or_aggregate_limit_plus_one(self):
        for contents, limits, reads in (
            ([b"x" * 11], (10, 15), [11]),
            ([b"x" * 6, b"x" * 6, b"x"], (10, 10), [11, 5]),
        ):
            with self.subTest(limits=limits):
                request, files = self.spooled_request(contents)
                with patch.object(DocumentRepository, "max_bytes", limits[0]), patch.object(DocumentRepository, "max_batch_bytes", limits[1]):
                    with self.assertRaises(HTTPException) as caught:
                        await server.upload_documents(request)
                self.assertEqual(caught.exception.status_code, 400)
                for file, bound in zip(files, reads):
                    file.read.assert_awaited_once_with(bound)
                for file in files[len(reads):]:
                    file.read.assert_not_awaited()
                self.assertTrue(all(file.file.closed for file in files))
        self.get_engine.assert_not_called()

    async def test_exact_limits_are_accepted(self):
        request, files = self.spooled_request([b"x" * 6, b"x" * 4])
        with patch.object(DocumentRepository, "max_bytes", 6), patch.object(DocumentRepository, "max_batch_bytes", 10):
            await server.upload_documents(request)
        self.engine.add_documents.assert_called_once()
        files[0].read.assert_awaited_once_with(7)
        files[1].read.assert_awaited_once_with(5)

    async def test_delete_is_one_call_and_missing_or_invalid_batches_do_not_partially_delete(self):
        response = await self.client.post("/api/documents/delete-batch", json={"ids": ["a", "b"]})
        self.assertEqual(response.status_code, 200)
        self.engine.remove_documents.assert_called_once_with(["a", "b"])
        self.engine.remove_documents.side_effect = DocumentNotFoundError("Chưa xóa tài liệu nào.")
        response = await self.client.post("/api/documents/delete-batch", json={"ids": ["a", "missing"]})
        self.assertEqual(response.status_code, 404)
        for ids in ([], ["a"] * 21):
            response = await self.client.post("/api/documents/delete-batch", json={"ids": ids})
            self.assertEqual(response.status_code, 422)

    async def test_build_failure_returns_retryable_response_and_releases_admission(self):
        for method, endpoint, kwargs in (
            ("add_documents", "/api/documents/upload-batch", {"files": self.files(), "data": {"metadata": "[{},{}]"}}),
            ("remove_documents", "/api/documents/delete-batch", {"json": {"ids": ["a", "b"]}}),
        ):
            operation = getattr(self.engine, method)
            operation.side_effect = OSError("disk full")
            response = await self.client.post(endpoint, **kwargs)
            self.assertEqual(response.status_code, 503)
            operation.side_effect = None
            response = await asyncio.wait_for(self.client.post(endpoint, **kwargs), 2)
            self.assertIn(response.status_code, (200, 201))

    async def test_cancelled_request_keeps_writer_admission_until_worker_finishes(self):
        entered, release = threading.Event(), threading.Event()
        def blocking(uploads):
            entered.set()
            if not release.wait(5):
                raise AssertionError("Writer was not released")
            return {"items": [{"id": "a"}]}
        self.engine.add_documents.side_effect = blocking
        first_request, first_files = self.spooled_request([b"%PDF-first"])
        queued_request, queued_files = self.spooled_request([b"%PDF-queued"])
        first = asyncio.create_task(server.upload_documents(first_request))
        self.assertTrue(await asyncio.to_thread(entered.wait, 2))
        first.cancel()
        queued = asyncio.create_task(server.upload_documents(queued_request))
        try:
            health = await asyncio.wait_for(self.client.get("/api/health"), 2)
            self.assertEqual(health.status_code, 200)
            queued_request.form.assert_not_called()
            queued_files[0].read.assert_not_awaited()
            self.assertFalse(first_files[0].file.closed)
            self.engine.add_documents.side_effect = None
        finally:
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await first
            await asyncio.wait_for(queued, 3)
        self.assertTrue(first_files[0].file.closed)
        queued_files[0].read.assert_awaited_once()

    async def test_real_engine_failed_batch_is_unchanged_and_can_be_retried(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        docs, index = root / "documents", root / "index.json"
        repository = DocumentRepository(docs)
        config = AppConfig(semantic_enabled=False)
        self.enterContext(patch("core.engine.DOCS", docs))
        self.enterContext(patch.object(repository, "extract", return_value=("Nội dung tài liệu đủ dài để lập chỉ mục.", 1)))
        _, searcher = build_index(config, return_searcher=True, index_path=index)
        self.engine = HocVuEngine.__new__(HocVuEngine)
        self.engine._corpus_lock = threading.RLock()
        self.engine.documents, self.engine.config, self.engine.searcher = repository, config, searcher
        def snapshot():
            return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}
        before = snapshot()
        with patch("core.engine.build_index", side_effect=OSError("disk full")):
            failed = await self.upload()
        self.assertEqual(failed.status_code, 503)
        self.assertEqual(snapshot(), before)
        self.assertIs(self.engine.searcher, searcher)
        with patch("core.engine.build_index", side_effect=lambda config, **kwargs: build_index(config, index_path=index, **kwargs)) as build:
            success = await self.upload()
            self.assertEqual(success.status_code, 201, success.text)
            build.assert_called_once()
        self.assertEqual(len(repository.list()), 2)
        ids = [item["id"] for item in success.json()["items"]]
        before = snapshot()
        with patch("core.engine.build_index", side_effect=OSError("disk full")):
            failed = await self.client.post("/api/documents/delete-batch", json={"ids": ids})
        self.assertEqual(failed.status_code, 503)
        self.assertEqual(snapshot(), before)

    async def test_cross_origin_batches_cannot_mutate_documents(self):
        for endpoint, kwargs in (
            ("/api/documents/upload-batch", {"files": self.files(), "data": {"metadata": "[{},{}]"}}),
            ("/api/documents/delete-batch", {"json": {"ids": ["a", "b"]}}),
        ):
            response = await self.client.post(endpoint, headers={"Origin": "https://other.example"}, **kwargs)
            self.assertEqual(response.status_code, 403)
        self.get_engine.assert_not_called()
