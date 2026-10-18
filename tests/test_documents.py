import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.documents import DocumentError, DocumentRepository
from core.splitter import split_regulation


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
        # The decision number is document metadata: it stays in the title,
        # version and every citation, but is not repeated in section headings.
        # Without a "Về việc" line the title still names the subject, taken
        # from the first heading.
        self.assertEqual(regulations[0].title, "Văn bản 12/QĐ-ĐH - Điều kiện bảo lưu")
        chunks = split_regulation(regulations[0], max_chars=800, overlap_sents=0)
        self.assertTrue(chunks)
        for chunk in chunks:
            self.assertEqual(chunk.reg_title, "Văn bản 12/QĐ-ĐH - Điều kiện bảo lưu")
            self.assertEqual(chunk.version, "Quyết định 12/QĐ-ĐH")
            self.assertEqual(chunk.art_heading, "Điều kiện bảo lưu")
            self.assertNotIn("12/QĐ-ĐH", chunk.text)
        # The text preview shows the extracted source, without the TOC.
        preview = self.repository.get_text(entry["id"])
        self.assertEqual(preview["title"], "Văn bản 12/QĐ-ĐH - Điều kiện bảo lưu")
        self.assertEqual(preview["text"], "## Điều kiện bảo lưu\nQuy chế đào tạo về điều kiện bảo lưu kết quả học tập của sinh viên.")

    def test_detected_decision_number_keeps_vietnamese_letters(self):
        text = "Số: 05/2026/TT-BGDĐT ngày 4 tháng 10 năm 2026\nVề việc: Đăng ký học phần học kỳ 1\nNội dung chi tiết."
        with patch.object(self.repository, "extract", return_value=(text, 1)):
            entry = self.repository.add("thong_bao.pdf", b"%PDF-1.7 detected", metadata={})
        self.assertEqual(entry["decision_number"], "05/2026/TT-BGDĐT")
        self.assertEqual(entry["document_date"], "2026-10-04")
        self.assertEqual(entry["title"], "Thông báo 05/2026/TT-BGDĐT - Đăng ký học phần học kỳ 1")

    def test_title_without_subject_line_uses_first_meaningful_heading(self):
        text = "\n".join([
            "## CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM",
            "## QUYẾT ĐỊNH",
            "Số: 34/QĐ-ĐHKT",
            "## Quy chế học bổng khuyến khích học tập",
            "Sinh viên đạt điểm trung bình từ 3.2 được xét học bổng.",
        ])
        with patch.object(self.repository, "extract", return_value=(text, 1)):
            entry = self.repository.add("scan_001.pdf", b"%PDF-1.7 heading", metadata={})
        self.assertEqual(entry["decision_number"], "34/QĐ-ĐHKT")
        self.assertEqual(entry["title"], "Văn bản 34/QĐ-ĐHKT - Quy chế học bổng khuyến khích học tập")
        regulation = self.repository.regulations()[0]
        self.assertEqual(regulation.title, entry["title"])
        self.assertEqual(regulation.version, "Quyết định 34/QĐ-ĐHKT")

    def test_subject_line_variants_take_precedence_over_heading_and_filename(self):
        for index, prefix in enumerate((
            "V/v ", "V/v: ", "Về việc ", "Về việc: ", "Tiêu đề: ",
            "  v/V:\t", "\tVỀ VIỆC ",
        )):
            with self.subTest(prefix=prefix):
                text = "\n".join([
                    "Số: 34/QĐ-ĐHKT",
                    "## QUYẾT ĐỊNH",
                    f"{prefix}ban hành Quy chế học bổng",
                    "## Điều 1. Phạm vi áp dụng",
                    "Sinh viên đạt điểm trung bình từ 3.2 được xét học bổng.",
                ])
                with patch.object(self.repository, "extract", return_value=(text, 1)):
                    entry = self.repository.add(
                        "scan_001.pdf", f"%PDF-1.7 subject {index}".encode(), metadata={},
                    )
                self.assertEqual(
                    entry["title"], "Thông báo 34/QĐ-ĐHKT - ban hành Quy chế học bổng",
                )
                self.assertEqual(self.repository.get_text(entry["id"])["title"], entry["title"])

    def test_subject_words_in_body_are_not_subject_lines(self):
        for index, phrase in enumerate(("V/v", "Về việc", "V/văn")):
            with self.subTest(phrase=phrase):
                text = f"## Quy chế học bổng\nNội dung {phrase} xét học bổng cho sinh viên."
                with patch.object(self.repository, "extract", return_value=(text, 1)):
                    entry = self.repository.add(
                        "scan_001.pdf", f"%PDF-1.7 body {index}".encode(),
                        metadata={"decision_number": "34/QĐ-ĐHKT"},
                    )
                self.assertEqual(entry["title"], "Văn bản 34/QĐ-ĐHKT - Quy chế học bổng")

    def test_title_without_subject_line_or_heading_uses_filename(self):
        text = "Nội dung quy định về lịch thi cuối kỳ, không có tiêu đề riêng."
        with patch.object(self.repository, "extract", return_value=(text, 1)):
            entry = self.repository.add("lich_thi_cuoi_ky.pdf", b"%PDF-1.7 filename", metadata={"decision_number": "7/TB-ĐH"})
        self.assertEqual(entry["decision_number"], "7/TB-ĐH")
        self.assertEqual(entry["title"], "Văn bản 7/TB-ĐH - lich thi cuoi ky")

    def test_title_keeps_subject_from_heading_that_starts_with_document_type(self):
        text = "## THÔNG BÁO HỌC BỔNG\nSố: 5/TB-ĐH\nSinh viên nộp hồ sơ trước ngày 20."
        with patch.object(self.repository, "extract", return_value=(text, 1)):
            entry = self.repository.add("scan_001.pdf", b"%PDF-1.7 typed heading", metadata={})
        self.assertEqual(entry["title"], "Văn bản 5/TB-ĐH - THÔNG BÁO HỌC BỔNG")

    def test_generic_scan_filenames_are_not_used_as_subjects(self):
        for name in ("scan_001.pdf", "IMG_2041.pdf", "Document (3).pdf", "tai_lieu.pdf"):
            self.assertEqual(DocumentRepository._subject_from_filename(name), "", name)
        self.assertEqual(DocumentRepository._subject_from_filename("lich_thi_cuoi_ky.pdf"), "lich thi cuoi ky")

    def test_title_keeps_bare_decision_number_when_no_subject_is_available(self):
        text = "Nội dung quy định đủ dài để lập chỉ mục an toàn."
        with patch.object(self.repository, "extract", return_value=(text, 1)):
            entry = self.repository.add("0123.pdf", b"%PDF-1.7 bare", metadata={"decision_number": "9/QĐ-ĐH"})
        self.assertEqual(entry["title"], "Văn bản 9/QĐ-ĐH")

    def test_article_headings_name_sections_and_preamble_uses_document_title(self):
        text = "\n".join([
            "Nội dung mở đầu của văn bản trước mục đầu tiên.",
            "## Thông báo 5/TB-ĐH - Lịch đăng ký",
            "Sinh viên đăng ký học phần trước ngày 15.",
            "**1. Lưu ý** Không nhận hồ sơ trễ hạn.",
        ])
        articles = DocumentRepository._make_articles(text, "Thông báo 5/TB-ĐH - Đăng ký học phần")
        self.assertEqual([article.heading for article in articles], [
            "Thông báo 5/TB-ĐH - Đăng ký học phần",
            "Thông báo 5/TB-ĐH - Lịch đăng ký",
            "1. Lưu ý",
        ])
        self.assertIn("Không nhận hồ sơ trễ hạn", articles[2].clauses[0].content)

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
