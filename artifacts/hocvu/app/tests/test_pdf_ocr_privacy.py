"""PDF ingestion stays local and never replaces native text with an LLM summary."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx
import pymupdf

from core.documents import DocumentError, DocumentRepository
from server import app as server


def make_pdf(texts):
    with pymupdf.open() as document:
        for text in texts:
            page = document.new_page()
            if text:
                page.insert_text((40, 40), text, fontsize=8)
            else:
                # Image-like content with no native text layer.
                page.draw_rect(pymupdf.Rect(50, 50, 150, 70), fill=(0, 0, 0))
        return document.tobytes()


class PdfPrivacyFixture:
    def prepare(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.repository = DocumentRepository(self.root / "library")
        for target in ("urllib.request.urlopen", "socket.socket.connect"):
            item = patch(target, side_effect=AssertionError("Document OCR must not use the network"))
            mock = item.start()
            self.addCleanup(item.stop)
            # Assert calls as well: a swallowed network exception must still fail.
            self.addCleanup(mock.assert_not_called)

    def source(self, texts):
        path = self.root / "source.pdf"
        path.write_bytes(make_pdf(texts))
        pages = [page.extract_text() or "" for page in self.repository._pdf_reader(path).pages]
        return path, pages


class PdfOcrPrivacyTests(PdfPrivacyFixture, unittest.TestCase):
    def setUp(self):
        self.prepare()

    def test_native_pdf_is_not_rendered_or_sent_out_for_any_llm_configuration(self):
        path, pages = self.source(["Native regulation: " + "preserve every clause and original link. " * 8])
        for backend, token in (
            ("local", "synthetic-ocr-test"), ("local", "your-gemini-api-key-here"),
            ("gemini", "synthetic-ocr-test"), ("openai", "synthetic-ocr-test"), ("local", ""),
        ):
            with self.subTest(backend=backend, placeholder=token == "your-gemini-api-key-here"):
                with (
                    patch.dict(os.environ, {"HV_LLM": backend, "GEMINI_API_KEY": token}),
                    patch.object(self.repository, "_extract_pdf_ocr") as ocr,
                    patch.object(pymupdf.Page, "get_pixmap") as render,
                    patch("core.settings.load_config") as load_config,
                ):
                    text, count = self.repository.extract(path, use_ocr=True)
                self.assertEqual(text, "\n".join(pages))
                self.assertEqual(count, 1)
                ocr.assert_not_called()
                render.assert_not_called()
                load_config.assert_not_called()

    def test_long_multipage_pdf_keeps_every_clause_amount_and_url(self):
        texts = [
            "\n".join(
                f"PAGE {page} LINE {line}: support 750000 VND; original clause https://school.example/form/{page}/{line}"
                for line in range(55)
            ) for page in range(8)
        ]
        path, pages = self.source(texts)
        with patch.dict(os.environ, {"HV_LLM": "gemini", "GEMINI_API_KEY": "synthetic-ocr-test"}):
            text, count = self.repository.extract(path, use_ocr=True)
        self.assertEqual(text, "\n".join(pages))
        self.assertEqual(count, 8)
        self.assertGreater(len(text), 30000)
        for page in range(8):
            self.assertIn(f"https://school.example/form/{page}/54", text)
            self.assertIn(f"PAGE {page} LINE 54", text)

    def test_mixed_pdf_only_ocrs_missing_text_and_keeps_page_order(self):
        path, pages = self.source([
            "Native first page, keep complete original evidence. " * 5,
            "",
            "Short native heading",
            "Native last page, retain the final clause and URL. " * 5,
        ])
        before = path.read_bytes()
        with patch.object(
            self.repository, "_ocr_pil_image_from_bytes",
            side_effect=["Nội dung trang scan thứ hai.", "Nội dung bổ sung của trang thứ ba."],
        ) as ocr:
            text, count = self.repository.extract(path, use_ocr=True)
        self.assertEqual(ocr.call_count, 2)
        self.assertTrue(all(call.args[0].startswith(b"\x89PNG\r\n\x1a\n") for call in ocr.call_args_list))
        self.assertEqual(count, 4)
        self.assertEqual(text, "\n".join([
            pages[0], "Nội dung trang scan thứ hai.",
            f"{pages[2]}\nNội dung bổ sung của trang thứ ba.".strip(), pages[3],
        ]))
        self.assertEqual(path.read_bytes(), before)

    def test_existing_automatic_scan_detection_uses_local_ocr_without_a_cloud_key(self):
        path, _ = self.source(["", ""])
        with (
            patch.dict(os.environ, {"HV_LLM": "local", "GEMINI_API_KEY": "your-gemini-api-key-here"}),
            patch.object(self.repository, "_ocr_pil_image_from_bytes", side_effect=["Scan page one", "Scan page two"]) as ocr,
        ):
            text, count = self.repository.extract(path, use_ocr=False)
        self.assertEqual(text, "Scan page one\nScan page two")
        self.assertEqual(count, 2)
        self.assertEqual(ocr.call_count, 2)

    def test_mixed_pdf_without_ocr_keeps_native_text_without_rendering_scan_pages(self):
        path, pages = self.source(["Native layer is kept without OCR. " * 8, ""])
        with patch.object(self.repository, "_extract_pdf_ocr") as ocr:
            text, count = self.repository.extract(path, use_ocr=False)
        self.assertEqual(text, "\n".join(pages))
        self.assertEqual(count, 2)
        ocr.assert_not_called()

    def test_text_threshold_is_consistent_and_never_discards_a_short_native_heading(self):
        path, pages = self.source(["A" * 39, "B" * 40, "", "Native final page. " * 10])
        with patch.object(self.repository, "_ocr_pil_image_from_bytes", side_effect=["OCR first", "OCR third"]) as ocr:
            text, _ = self.repository.extract(path, use_ocr=True)
        self.assertEqual(ocr.call_count, 2)
        self.assertEqual(text, "\n".join([
            f"{pages[0]}\nOCR first".strip(), pages[1], "OCR third", pages[3],
        ]))

    def test_local_failure_is_explicit_and_cleans_failed_upload_instead_of_using_a_cloud_fallback(self):
        content = make_pdf([""])
        with patch.object(self.repository, "_ocr_pil_image_from_bytes", side_effect=DocumentError("Không tìm thấy Tesseract OCR trên máy chủ.")):
            with self.assertRaisesRegex(DocumentError, "Tesseract"):
                self.repository.add("scan.pdf", content, use_ocr=True)
        self.assertEqual(self.repository.list(), [])
        self.assertEqual(list(self.repository.root.glob("*.pdf")), [])
        self.assertEqual(list((self.repository.root / "extracted").iterdir()), [])

    def test_legacy_summarized_cache_is_reextracted_from_original_without_changing_identity(self):
        path, pages = self.source(["Original regulation with complete clause and final URL https://school.example/final. " * 5])
        content = path.read_bytes()
        entry = self.repository.add("regulation.pdf", content, use_ocr=True)
        entries = self.repository.list()
        entries[0]["extraction_version"] = 4
        self.repository._write_manifest(entries)
        self.repository._extracted_path(entry["id"]).write_text("Old cloud summary omitted most clauses.", encoding="utf-8")
        regulations = self.repository.regulations()
        self.assertEqual(self.repository.get_text(entry["id"])["text"], "\n".join(pages))
        self.assertEqual(regulations[0].rid, entry["rid"])
        upgraded = self.repository.list()[0]
        self.assertEqual(upgraded, {**entry, "extraction_version": self.repository.extraction_version})
        self.assertEqual((self.repository.root / entry["stored_name"]).read_bytes(), content)

    def test_missing_text_cache_is_recreated_locally(self):
        path, pages = self.source(["Complete original source text, retained for citations. " * 5])
        entry = self.repository.add("regulation.pdf", path.read_bytes(), use_ocr=True)
        self.repository._extracted_path(entry["id"]).unlink()
        self.assertEqual(self.repository.get_text(entry["id"])["text"], "\n".join(pages))

    def test_example_gemini_key_is_empty_and_local_is_still_the_default(self):
        settings = dict(
            line.split("=", 1) for line in (Path(__file__).resolve().parents[1] / ".env.example").read_text().splitlines()
            if line and not line.startswith("#") and "=" in line
        )
        self.assertEqual(settings["GEMINI_API_KEY"].strip(), "")
        self.assertEqual(settings["HV_LLM"], "local")


class PdfOcrPrivacyApiTests(PdfPrivacyFixture, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.prepare()

    async def test_upload_with_ocr_and_placeholder_key_keeps_complete_native_text(self):
        path, pages = self.source([
            "First original page https://school.example/first with native text. " * 5,
            "Last original page https://school.example/last with native text. " * 5,
        ])
        with (
            patch.dict(os.environ, {"HV_LLM": "local", "GEMINI_API_KEY": "your-gemini-api-key-here"}),
            patch.object(server.config, "api_token", "synthetic-ocr-api"),
            patch.object(server, "requires_api_token", True),
            patch.object(server, "browser_auth_enabled", False),
            patch.object(server, "request_limiter", server.SlidingWindowLimiter()),
            patch.object(server, "get_engine") as get_engine,
        ):
            get_engine.return_value.add_document.side_effect = self.repository.add
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=server.app), base_url="http://test",
                headers={"X-HocVu-Token": "synthetic-ocr-api", "Origin": "http://test"},
            ) as client:
                response = await client.post(
                    "/api/documents/upload", data={"ocr": "true"},
                    files={"file": ("regulation.pdf", path.read_bytes(), "application/pdf")},
                )
        self.assertEqual(response.status_code, 201)
        entry = response.json()
        self.assertEqual(entry["pages"], 2)
        self.assertTrue(entry["ocr"])
        self.assertEqual(self.repository.get_text(entry["id"])["text"], "\n".join(pages))
