import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.documents import DocumentError, DocumentRepository


class DocumentRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repository = DocumentRepository(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_accepts_docx_and_builds_regulation(self):
        # A minimal valid DOCX package, generated without external libraries.
        source = self.root / "input.docx"
        document_xml = '''<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:pPr><w:pStyle w:val="TOC1"/></w:pPr><w:r><w:t>MỤC LỤC</w:t></w:r></w:p><w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr><w:r><w:t>Điều kiện bảo lưu</w:t></w:r></w:p><w:p><w:r><w:t>Quy chế đào tạo về điều kiện bảo lưu kết quả học tập của sinh viên.</w:t></w:r></w:p></w:body></w:document>'''.encode("utf-8")
        with __import__("zipfile").ZipFile(source, "w") as archive:
            archive.writestr("word/document.xml", document_xml)
        entry = self.repository.add("quy_che.docx", source.read_bytes(), metadata={
            "order": "2", "decision_number": "12/QĐ-ĐH", "article_clause": "Điều 4, Khoản 2", "document_date": "2026-10-04",
        })
        regulations = self.repository.regulations()
        self.assertEqual(entry["format"], "DOCX")
        self.assertEqual(len(regulations), 1)
        self.assertTrue((self.root / "extracted" / f"{entry['id']}.txt").exists())
        self.assertEqual(regulations[0].articles[0].heading, "Điều kiện bảo lưu")
        self.assertIn("bảo lưu", regulations[0].articles[0].clauses[0].content)
        self.assertEqual(entry["order"], 2)
        self.assertEqual(entry["decision_number"], "12/QĐ-ĐH")
        self.assertEqual(regulations[0].version, "Quyết định 12/QĐ-ĐH")
        self.assertEqual(regulations[0].valid_from, "2026-10-04")

    def test_pdf_reader_dependency_error_is_actionable(self):
        with patch.dict("sys.modules", {"pypdf": None}):
            with self.assertRaises(DocumentError) as error:
                self.repository.extract(self.root / "missing.pdf")
        self.assertIn("pip install", str(error.exception))

    def test_rejects_wrong_format(self):
        with self.assertRaises(DocumentError):
            self.repository.add("quy_che.txt", b"not a supported document")

    def test_image_requires_opt_in_and_records_ocr(self):
        with self.assertRaises(DocumentError):
            self.repository.add("scan.png", b"\x89PNG\r\n\x1a\n")
        with patch.object(self.repository, "_extract_image_ocr", return_value="Nội dung ảnh đã OCR đủ dài để lập chỉ mục."):
            entry = self.repository.add("scan.png", b"\x89PNG\r\n\x1a\n", use_ocr=True)
        self.assertEqual(entry["format"], "PNG")
        self.assertTrue(entry["ocr"])

    def test_uploaded_date_is_stable_when_effective_date_is_not_provided(self):
        with patch.object(self.repository, "extract", return_value=("Nội dung quy định đủ dài để lập chỉ mục an toàn.", 1)):
            entry = self.repository.add("van_ban.pdf", b" \n%PDF-1.7", metadata={})
        regulation = self.repository.regulations()[0]
        self.assertEqual(regulation.valid_from, entry["uploaded_at"][:10])

    def test_docx_heading_level_five_is_retained(self):
        source = self.root / "heading.docx"
        document_xml = '''<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:pPr><w:pStyle w:val="Heading5"/></w:pPr><w:r><w:t>Mục quan trọng</w:t></w:r></w:p><w:p><w:r><w:t>Nội dung điều khoản đầy đủ.</w:t></w:r></w:p></w:body></w:document>'''.encode("utf-8")
        with __import__("zipfile").ZipFile(source, "w") as archive:
            archive.writestr("word/document.xml", document_xml)
        text = self.repository._extract_docx(source)
        self.assertIn("##### Mục quan trọng", text)

    def test_numbered_content_line_is_not_mistaken_for_a_table_of_contents(self):
        self.assertFalse(self.repository._is_table_of_contents_line("1. Quy định áp dụng cho năm 2026"))
        self.assertTrue(self.repository._is_table_of_contents_line("Điều 1. Phạm vi ........ 3"))

    def test_duplicate_content_is_rejected_before_extraction(self):
        content = b"PK\x03\x04 duplicate document"
        with patch.object(self.repository, "extract", return_value=("Nội dung quy định đủ dài để lập chỉ mục an toàn.", 1)):
            self.repository.add("mot.docx", content)
            with self.assertRaisesRegex(DocumentError, "trùng"):
                self.repository.add("hai.docx", content)

    def test_corrupt_manifest_recovers_from_last_backup(self):
        self.repository._write_manifest([{"id": "old", "order": 1}])
        self.repository._write_manifest([{"id": "new", "order": 2}])
        self.repository.manifest.write_text("{broken", encoding="utf-8")
        self.assertEqual(self.repository.list(), [{"id": "old", "order": 1}])


if __name__ == "__main__":
    unittest.main()
