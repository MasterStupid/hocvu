"""Date edits preserve the upload and synchronously update searchable validity."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx

from core.documents import DocumentError, DocumentNotFoundError, DocumentRepository
from core.engine import HocVuEngine, build_index as real_build_index
from core.searcher import HybridSearcher
from core.settings import AppConfig
from server import app as server


class DateEditFixture:
    def prepare(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.index = self.root / "index.json"
        config = AppConfig(semantic_enabled=False)
        searcher = HybridSearcher(config)
        searcher.build([])
        for target, value in (
            ("core.engine.DOCS", self.root / "documents"),
            ("core.engine.SESSION_DB", self.root / "sessions.db"),
        ):
            item = patch(target, value)
            item.start()
            self.addCleanup(item.stop)
        self.engine = HocVuEngine(config, searcher)
        self.repository = self.engine.documents
        with patch.object(self.repository, "extract", return_value=(
            "## Hỗ trợ nghiên cứu thiên văn\nSinh viên nghiên cứu thiên văn được hỗ trợ 700000 đồng mỗi tháng.", 1,
        )):
            self.entry = self.repository.add(
                "nghien_cuu.pdf", b"%PDF-1.7 synthetic research",
                metadata={"document_date": "2026-12-31", "decision_number": "12/QĐ-ĐH", "order": "3"},
            )
        self.original = (self.repository.root / self.entry["stored_name"]).read_bytes()
        self.text = self.repository._extracted_path(self.entry["id"]).read_bytes()
        # Route the real builder to isolated fixture storage, never the app DB/index.
        def rebuild(config, **kwargs):
            return real_build_index(config, index_path=self.index, **kwargs)
        item = patch("core.engine.build_index", side_effect=rebuild)
        self.build = item.start()
        self.addCleanup(item.stop)
        self.engine.rebuild_index()
        self.build.reset_mock()

    def uploaded_hits(self, searcher=None, ref_date="2026-10-20"):
        return [
            hit for hit in (searcher or self.engine.searcher).search(
                "hỗ trợ nghiên cứu thiên văn", 100, ref_date,
            ) if hit.chunk.rid == self.entry["rid"]
        ]

    def assert_files_unchanged(self):
        self.assertEqual((self.repository.root / self.entry["stored_name"]).read_bytes(), self.original)
        self.assertEqual(self.repository._extracted_path(self.entry["id"]).read_bytes(), self.text)
        self.assertEqual(len(list(self.repository.root.glob("*.pdf"))), 1)


class DocumentDateEditTests(DateEditFixture, unittest.TestCase):
    def setUp(self):
        self.prepare()

    def test_edit_preserves_every_field_except_date_and_rebuilds_live_and_saved_index(self):
        self.assertFalse(self.uploaded_hits())
        old_searcher = self.engine.searcher
        item = self.engine.update_document_date(self.entry["id"], "20261001")
        expected = {**self.entry, "document_date": "2026-10-01"}
        self.assertEqual(item, expected)
        self.assertEqual(self.repository.list(), [expected])
        self.assertIsNot(self.engine.searcher, old_searcher)
        self.build.assert_called_once_with(self.engine.config, return_searcher=True)
        self.assertTrue(self.uploaded_hits())
        self.assertFalse(self.uploaded_hits(ref_date="2026-09-30"))
        self.assertTrue(self.uploaded_hits(ref_date="2026-10-01"))
        restored = HybridSearcher.load(str(self.index), self.engine.config)
        self.assertTrue(self.uploaded_hits(restored))
        self.assertEqual(DocumentRepository(self.repository.root).list(), [expected])
        self.assert_files_unchanged()
        listing = next(item for item in self.engine.list_documents() if item.get("id") == self.entry["id"])
        self.assertEqual(listing["valid_from"], "2026-10-01")

    def test_invalid_and_empty_dates_do_not_change_metadata_or_reindex(self):
        for value in ("2026-02-31", "2026-10-35", "2025-02-29", "bad", "", "   "):
            with self.subTest(value=value):
                with self.assertRaises(DocumentError):
                    self.engine.update_document_date(self.entry["id"], value)
                self.assertEqual(self.repository.list(), [self.entry])
        self.build.assert_not_called()
        self.assert_files_unchanged()

    def test_leap_day_is_accepted(self):
        item = self.engine.update_document_date(self.entry["id"], "2024-02-29")
        self.assertEqual(item["document_date"], "2024-02-29")
        self.assertTrue(self.uploaded_hits(ref_date="2024-02-29"))

    def test_missing_document_cannot_edit_builtin_regulations(self):
        for item_id in ("missing", "QD-DTDC-HPU-2026"):
            with self.assertRaises(DocumentNotFoundError):
                self.engine.update_document_date(item_id, "2026-10-01")
        self.build.assert_not_called()
        self.assertEqual(self.repository.list(), [self.entry])

    def test_reindex_failure_rolls_back_only_date_and_keeps_live_index(self):
        old_searcher = self.engine.searcher
        saved_index = self.index.read_bytes()
        with patch("core.engine.build_index", side_effect=RuntimeError("synthetic failure")):
            with self.assertRaises(RuntimeError):
                self.engine.update_document_date(self.entry["id"], "2026-10-01")
        self.assertEqual(self.repository.list(), [self.entry])
        self.assertIs(self.engine.searcher, old_searcher)
        self.assertEqual(self.index.read_bytes(), saved_index)
        self.assert_files_unchanged()

    def test_legacy_bad_date_can_be_corrected_without_reupload(self):
        entries = self.repository.list()
        entries[0]["document_date"] = "2026-02-31"
        self.repository._write_manifest(entries)
        self.engine.update_document_date(self.entry["id"], "2026-02-28")
        self.assertTrue(self.uploaded_hits(ref_date="2026-02-28"))
        self.assertEqual(self.repository.list()[0]["id"], self.entry["id"])
        self.assert_files_unchanged()

    def test_failed_reindex_does_not_undo_unrelated_metadata_changes(self):
        def fail_after_metadata_edit(*args, **kwargs):
            entries = self.repository.list()
            entries[0]["order"] = 9
            self.repository._write_manifest(entries)
            raise RuntimeError("synthetic failure")
        with patch("core.engine.build_index", side_effect=fail_after_metadata_edit):
            with self.assertRaises(RuntimeError):
                self.engine.update_document_date(self.entry["id"], "2026-10-01")
        self.assertEqual(self.repository.list(), [{**self.entry, "order": 9}])

    def test_rollback_preserves_an_absent_legacy_date_field(self):
        entries = self.repository.list()
        entries[0].pop("document_date")
        self.repository._write_manifest(entries)
        with patch("core.engine.build_index", side_effect=RuntimeError("synthetic failure")):
            with self.assertRaises(RuntimeError):
                self.engine.update_document_date(self.entry["id"], "2026-10-01")
        self.assertEqual(self.repository.list(), entries)

    def test_rollback_can_restore_a_legacy_invalid_date(self):
        entries = self.repository.list()
        entries[0]["document_date"] = "2026-02-31"
        self.repository._write_manifest(entries)
        with patch("core.engine.build_index", side_effect=RuntimeError("synthetic failure")):
            with self.assertRaises(RuntimeError):
                self.engine.update_document_date(self.entry["id"], "2026-02-28")
        self.assertEqual(self.repository.list()[0]["document_date"], "2026-02-31")


class DocumentDateEditApiTests(DateEditFixture, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.prepare()
        for item in (
            patch.object(server.config, "api_token", "synthetic-date-edit"),
            patch.object(server.config, "rate_limit_per_minute", 120),
            patch.object(server, "requires_api_token", True),
            patch.object(server, "browser_auth_enabled", True),
            patch.object(server, "request_limiter", server.SlidingWindowLimiter()),
            patch.object(server, "get_engine", return_value=self.engine),
        ):
            item.start()
            self.addCleanup(item.stop)
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app), base_url="http://test",
        )
        self.addAsyncCleanup(self.client.aclose)
        self.url = f"/api/documents/{self.entry['id']}/date"
        self.headers = {"Origin": "http://test", "X-HocVu-Token": "synthetic-date-edit"}

    async def test_header_client_can_edit_date_and_search_changes_immediately(self):
        response = await self.client.patch(self.url, headers=self.headers, json={"document_date": "2026-10-01"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {**self.entry, "document_date": "2026-10-01"})
        self.assertTrue(self.uploaded_hits())
        self.assert_files_unchanged()

    async def test_basic_authenticated_browser_can_edit_date(self):
        response = await self.client.patch(
            self.url, auth=("hocvu", "synthetic-date-edit"), headers={"Origin": "http://test"},
            json={"document_date": "2026-10-01"},
        )
        self.assertEqual(response.status_code, 200)

    async def test_missing_wrong_and_malformed_authentication_cannot_write(self):
        for headers in (
            {"Origin": "http://test"},
            {"Origin": "http://test", "X-HocVu-Token": "wrong"},
            {"Origin": "http://test", "Authorization": "Basic !!!"},
        ):
            response = await self.client.patch(self.url, headers=headers, json={"document_date": "2026-10-01"})
            self.assertEqual(response.status_code, 401)
        self.build.assert_not_called()
        self.assertEqual(self.repository.list(), [self.entry])

    async def test_cross_site_changes_and_basic_without_origin_are_rejected(self):
        for headers, auth in (
            ({**self.headers, "Origin": "https://attacker.example"}, None),
            ({**self.headers, "Sec-Fetch-Site": "cross-site"}, None),
            ({}, ("hocvu", "synthetic-date-edit")),
        ):
            response = await self.client.patch(
                self.url, headers=headers, auth=auth, json={"document_date": "2026-10-01"},
            )
            self.assertEqual(response.status_code, 403)
        self.build.assert_not_called()
        self.assertEqual(self.repository.list(), [self.entry])

    async def test_calendar_errors_and_request_validation_cannot_write_other_fields(self):
        for payload, expected in (
            ({"document_date": "2026-02-31"}, 400),
            ({"document_date": "2026-10-35"}, 400),
            ({"document_date": " "}, 400),
            ({"document_date": ""}, 422),
            ({}, 422),
            ({"document_date": None}, 422),
            ({"document_date": "2026-10-01", "rid": "overwrite"}, 422),
        ):
            response = await self.client.patch(self.url, headers=self.headers, json=payload)
            self.assertEqual(response.status_code, expected, response.text)
        self.assertEqual(self.repository.list(), [self.entry])
        self.build.assert_not_called()

    async def test_missing_document_returns_404(self):
        response = await self.client.patch(
            "/api/documents/missing/date", headers=self.headers, json={"document_date": "2026-10-01"},
        )
        self.assertEqual(response.status_code, 404)

    async def test_reindex_failure_is_explicit_and_does_not_commit_the_date(self):
        with patch("core.engine.build_index", side_effect=RuntimeError("private backend error")):
            response = await self.client.patch(
                self.url, headers=self.headers, json={"document_date": "2026-10-01"},
            )
        self.assertEqual(response.status_code, 503)
        self.assertIn("ngày áp dụng cũ được giữ nguyên", response.json()["detail"])
        self.assertNotIn("private backend error", response.text)
        self.assertEqual(self.repository.list(), [self.entry])

    async def test_new_editor_asset_is_protected_by_browser_auth(self):
        response = await self.client.get("/document-date-editor.js")
        self.assertEqual(response.status_code, 401)
        response = await self.client.get("/document-date-editor.js", auth=("hocvu", "synthetic-date-edit"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("createDateEditor", response.text)
