"""OCR date errors must fail ingestion, never create unsearchable ready rows."""
from datetime import date
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx

from core.documents import DocumentError, DocumentRepository
from core.searcher import HybridSearcher
from core.settings import AppConfig
from core.splitter import split_regulation
from server import app as server


class DocumentDateTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.repository = DocumentRepository(self.root)

    @staticmethod
    def text(day, month, year):
        return (
            f"Ngày {day} tháng {month} năm {year:04d}\n"
            "## Điều kiện bảo lưu\n"
            "Sinh viên được bảo lưu kết quả học tập tối đa bốn học kỳ."
        )

    def upload(self, text, metadata=None):
        with patch.object(self.repository, "extract", return_value=(text, 1)):
            return self.repository.add("quy_dinh.pdf", b"%PDF-1.7 synthetic", metadata=metadata)

    def test_invalid_auto_dates_never_create_ready_documents_or_orphan_files(self):
        for day, month, year in (
            (31, 2, 2026), (35, 10, 2026), (29, 2, 2025),
            (29, 2, 1900), (31, 4, 2026), (0, 10, 2026),
            (1, 0, 2026), (1, 13, 2026), (1, 1, 0),
        ):
            with self.subTest(day=day, month=month, year=year):
                with self.assertRaisesRegex(DocumentError, "Ngày tự nhận diện.*không hợp lệ.*ngày áp dụng"):
                    self.upload(self.text(day, month, year))
                self.assertEqual(self.repository.list(), [])
                self.assertEqual(list(self.root.glob("*.pdf")), [])
                self.assertEqual(list((self.root / "extracted").iterdir()), [])
                self.assertFalse(self.repository.manifest.exists())

    def test_valid_detected_dates_are_canonical_and_searchable(self):
        for day, month, year in ((4, 10, 2026), (29, 2, 2024), (29, 2, 2000), (31, 12, 2026)):
            with self.subTest(day=day, month=month, year=year):
                # Independent repositories avoid duplicate-upload detection.
                repository = DocumentRepository(self.root / f"{year}-{month}-{day}")
                with patch.object(repository, "extract", return_value=(self.text(day, month, year), 1)):
                    entry = repository.add("quy_dinh.pdf", b"%PDF-1.7 valid date")
                expected = date(year, month, day).isoformat()
                self.assertEqual(entry["status"], "ready")
                self.assertEqual(entry["document_date"], expected)
                self.assertEqual(repository.list()[0]["document_date"], expected)
                regulation = repository.regulations()[0]
                self.assertEqual(regulation.valid_from, expected)
                searcher = HybridSearcher(AppConfig(semantic_enabled=False))
                searcher.build(split_regulation(regulation, 800, 1))
                hits = searcher.search("bảo lưu", 5, expected)
                self.assertTrue(hits)
                self.assertTrue(all(hit.chunk.rid == entry["rid"] for hit in hits))

    def test_explicit_valid_date_overrides_bad_ocr_date(self):
        entry = self.upload(self.text(31, 2, 2026), {"document_date": "2026-02-28"})
        self.assertEqual(entry["document_date"], "2026-02-28")
        regulation = self.repository.regulations()[0]
        self.assertEqual(regulation.valid_from, "2026-02-28")
        searcher = HybridSearcher(AppConfig(semantic_enabled=False))
        searcher.build(split_regulation(regulation, 800, 1))
        self.assertTrue(searcher.search("bảo lưu", 5, "2026-02-28"))

    def test_invalid_explicit_date_is_rejected_before_extraction(self):
        for value in ("2026-02-31", "2026-10-35", "2025-02-29", "not-a-date"):
            with self.subTest(value=value):
                with patch.object(self.repository, "extract") as extract:
                    with self.assertRaisesRegex(DocumentError, "Ngày áp dụng"):
                        self.repository.add(
                            "quy_dinh.pdf", b"%PDF-1.7 explicit",
                            metadata={"document_date": value},
                        )
                    extract.assert_not_called()
                self.assertEqual(self.repository.list(), [])
                self.assertEqual(list(self.root.glob("*.pdf")), [])

    def test_valid_noncanonical_manual_date_is_stored_in_searchable_iso_form(self):
        entry = self.upload(self.text(31, 2, 2026), {"document_date": "20261004"})
        self.assertEqual(entry["document_date"], "2026-10-04")
        regulation = self.repository.regulations()[0]
        searcher = HybridSearcher(AppConfig(semantic_enabled=False))
        searcher.build(split_regulation(regulation, 800, 1))
        self.assertTrue(searcher.search("bảo lưu", 5, "2026-10-04"))

    def test_no_detected_date_keeps_the_stable_upload_date_fallback(self):
        entry = self.upload("## Quy định bảo lưu\nSinh viên được bảo lưu tối đa bốn học kỳ.")
        self.assertIsNone(entry["document_date"])
        for _ in range(2):
            self.assertEqual(self.repository.regulations()[0].valid_from, entry["uploaded_at"][:10])

    def test_failed_upload_can_be_retried_with_a_correct_manual_date(self):
        text = self.text(35, 10, 2026)
        with self.assertRaises(DocumentError):
            self.upload(text)
        entry = self.upload(text, {"document_date": "2026-10-25"})
        self.assertEqual(entry["status"], "ready")
        self.assertEqual(len(self.repository.list()), 1)
        self.assertEqual(len(list(self.root.glob("*.pdf"))), 1)
        self.assertEqual(len(list((self.root / "extracted").iterdir())), 1)

    def test_bad_dates_do_not_make_search_filter_fail_open(self):
        entry = self.upload(self.text(4, 10, 2026))
        chunk = split_regulation(self.repository.regulations()[0], 800, 1)[0]
        chunk.valid_from = "2026-02-31"
        self.assertFalse(HybridSearcher._is_valid(chunk, "2026-10-20"))
        chunk.valid_from = entry["document_date"]
        self.assertFalse(HybridSearcher._is_valid(chunk, "2026-10-03"))
        self.assertTrue(HybridSearcher._is_valid(chunk, "2026-10-04"))


class DocumentDateApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_auto_date_returns_actionable_400_and_can_be_corrected(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = DocumentRepository(Path(directory))
            with (
                patch.object(server.config, "api_token", "synthetic-date-test"),
                patch.object(server, "requires_api_token", True),
                patch.object(server, "browser_auth_enabled", False),
                patch.object(server, "request_limiter", server.SlidingWindowLimiter()),
                patch.object(server, "get_engine") as get_engine,
                patch.object(repository, "extract", return_value=(DocumentDateTests.text(31, 2, 2026), 1)),
            ):
                get_engine.return_value.add_document.side_effect = repository.add
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=server.app), base_url="http://test",
                    headers={"X-HocVu-Token": "synthetic-date-test", "Origin": "http://test"},
                ) as client:
                    response = await client.post(
                        "/api/documents/upload",
                        files={"file": ("quy_dinh.pdf", b"%PDF-1.7 auto-date")},
                    )
                    self.assertEqual(response.status_code, 400)
                    self.assertIn("31/02/2026", response.json()["detail"])
                    self.assertIn("ngày áp dụng chính xác", response.json()["detail"])
                    self.assertEqual(repository.list(), [])
                    corrected = await client.post(
                        "/api/documents/upload", data={"document_date": "2026-02-28"},
                        files={"file": ("quy_dinh.pdf", b"%PDF-1.7 auto-date")},
                    )
                    self.assertEqual(corrected.status_code, 201)
                    self.assertEqual(corrected.json()["document_date"], "2026-02-28")
