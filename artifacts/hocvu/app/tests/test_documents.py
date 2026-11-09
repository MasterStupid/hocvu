import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from xml.sax.saxutils import escape

from core.documents import DocumentError, DocumentRepository
from core.splitter import split_regulation


def make_subject_docx(paragraphs):
    """Build a small Word package with real paragraph styles and text runs."""
    blocks = []
    for text, heading in paragraphs:
        style = f'<w:pPr><w:pStyle w:val="Heading{heading}"/></w:pPr>' if heading else ""
        blocks.append(f"<w:p>{style}<w:r><w:t>{escape(text)}</w:t></w:r></w:p>")
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", (
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
            '</Types>'
        ))
        archive.writestr("_rels/.rels", (
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            '</Relationships>'
        ))
        archive.writestr("word/_rels/document.xml.rels", (
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            '</Relationships>'
        ))
        archive.writestr("word/styles.xml", (
            '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            + "".join(
                f'<w:style w:type="paragraph" w:styleId="Heading{level}">'
                f'<w:name w:val="heading {level}"/><w:pPr><w:outlineLvl w:val="{level - 1}"/></w:pPr></w:style>'
                for level in (1, 2)
            ) + '</w:styles>'
        ))
        archive.writestr("word/document.xml", (
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f'<w:body>{"".join(blocks)}<w:sectPr/></w:body></w:document>'
        ))
    return content.getvalue()


def make_subject_pdf(paragraphs):
    """Render actual Vietnamese text with embedded fonts, without system fonts."""
    import pymupdf

    content = io.BytesIO()
    writer = pymupdf.DocumentWriter(content)
    html = "".join(
        f"<h{heading}>{escape(text)}</h{heading}>" if heading else f"<p>{escape(text)}</p>"
        for text, heading in paragraphs
    )
    story = pymupdf.Story(html=html)
    device = writer.begin_page(pymupdf.Rect(0, 0, 595, 842))
    more, _ = story.place(pymupdf.Rect(40, 40, 555, 802))
    if more:
        raise AssertionError("Subject fixture must fit on one PDF page")
    story.draw(device)
    writer.end_page()
    writer.close()
    with pymupdf.open(stream=content.getvalue(), filetype="pdf") as document:
        document.subset_fonts()
        return document.tobytes(garbage=4, deflate=True)


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
            self.assertEqual(chunk.aid, "Điều 4")
            self.assertEqual(chunk.clause_ids, ["2"])
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

    def test_subject_titles_survive_real_docx_and_pdf_extraction(self):
        subject = "ban hành Quy chế học bổng"
        for extension, generate in (("docx", make_subject_docx), ("pdf", make_subject_pdf)):
            for prefix, heading in (("Về việc ", 0), ("V/v ", 0), ("Về việc ", 2), ("V/v ", 2)):
                with self.subTest(format=extension, prefix=prefix, heading=heading):
                    paragraphs = [
                        ("Số: 34/QĐ-ĐHKT", 0),
                        ("QUYẾT ĐỊNH", 1),
                        (f"{prefix}{subject}", heading),
                        ("Điều 1. Phạm vi áp dụng", 2),
                        ("Sinh viên đạt điểm trung bình từ 3.2 được xét học bổng.", 0),
                    ]
                    # Each case has its own manifest so identical extracted text
                    # in differently styled files cannot trigger duplicate checks.
                    with tempfile.TemporaryDirectory() as root:
                        repository = DocumentRepository(Path(root))
                        entry = repository.add(f"lich_thi_cuoi_ky.{extension}", generate(paragraphs))
                        expected = f"Thông báo 34/QĐ-ĐHKT - {subject}"
                        self.assertEqual(entry["title"], expected)
                        self.assertEqual(entry["decision_number"], "34/QĐ-ĐHKT")
                        self.assertEqual(entry["format"], extension.upper())
                        self.assertEqual(entry["pages"], 1)
                        self.assertFalse(entry["ocr"])

                        # Read a new repository instance, not just add()'s return
                        # value, to check manifest and extracted-text persistence.
                        reopened = DocumentRepository(Path(root))
                        self.assertEqual(reopened.list()[0]["title"], expected)
                        preview = reopened.get_text(entry["id"])
                        self.assertEqual(preview["title"], expected)
                        extracted_subject = f"{prefix}{subject}"
                        if extension == "docx" and heading:
                            extracted_subject = f"## {extracted_subject}"
                        self.assertIn(extracted_subject, preview["text"])
                        self.assertIn("QUYẾT ĐỊNH", preview["text"])
                        self.assertIn("Điều 1. Phạm vi áp dụng", preview["text"])
                        self.assertEqual(reopened.regulations()[0].title, expected)

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

    def test_wrapped_subject_stops_before_headings_or_body(self):
        endings = (
            "## Điều 1. Phạm vi áp dụng",
            "**Điều 1. Phạm vi áp dụng**",
            "Điều 1. Phạm vi áp dụng",
            "điều 1. phạm vi áp dụng",
            "CHƯƠNG I. QUY ĐỊNH CHUNG",
            "1. Phạm vi áp dụng",
            "a) Phạm vi áp dụng",
            "- Sinh viên nộp hồ sơ trước ngày 20.",
            "Căn cứ Quy chế đào tạo hiện hành;",
            "căn cứ Quy chế đào tạo hiện hành;",
            "Sinh viên nộp hồ sơ trước ngày 20.",
            "sinh viên nộp hồ sơ trước ngày 20.",
            "nội dung chi tiết của thông báo.",
            "",
        )
        for index, ending in enumerate(endings):
            with self.subTest(ending=ending):
                text = "\n".join([
                    "Số: 34/QĐ-ĐHKT",
                    "Về việc: ban hành Quy chế học bổng",
                    "  khuyến khích học tập năm 2026",
                    ending,
                    "không được đưa nội dung này vào tiêu đề",
                ])
                with patch.object(self.repository, "extract", return_value=(text, 1)):
                    entry = self.repository.add(
                        "scan_001.pdf", f"%PDF-1.7 wrapped {index}".encode(),
                    )
                self.assertEqual(
                    entry["title"],
                    "Thông báo 34/QĐ-ĐHKT - ban hành Quy chế học bổng khuyến khích học tập năm 2026",
                )
                self.assertEqual(self.repository.get_text(entry["id"])["title"], entry["title"])
                self.assertEqual(self.repository.regulations()[-1].title, entry["title"])

    def test_wrapped_subject_prefixes_and_line_endings(self):
        for index, prefix in enumerate(("V/v ", "V/v: ", "Về việc ", "Về việc: ", "Tiêu đề: ")):
            for newline in ("\n", "\r\n", "\r"):
                with self.subTest(prefix=prefix, newline=repr(newline)):
                    text = newline.join([
                        f"{prefix}ban hành Quy chế",
                        "học bổng khuyến khích học tập",
                        "cho năm học 2026.",
                        "không lấy thêm văn bản sau dấu chấm",
                    ])
                    with patch.object(self.repository, "extract", return_value=(text, 1)):
                        entry = self.repository.add(
                            "scan_001.pdf", f"%PDF-1.7 prefix {index} {newline!r}".encode(),
                            metadata={"decision_number": "34/QĐ-ĐHKT"},
                        )
                    self.assertEqual(
                        entry["title"],
                        "Thông báo 34/QĐ-ĐHKT - ban hành Quy chế học bổng khuyến khích học tập cho năm học 2026.",
                    )

    def test_single_line_subject_does_not_consume_body_or_blank_lines(self):
        for index, (subject, following) in enumerate((
            ("ban hành Quy chế học bổng", "Sinh viên nộp hồ sơ trước ngày 20."),
            ("ban hành Quy chế học bổng", "nội dung chi tiết của thông báo."),
            ("ban hành Quy chế học bổng", "\nkhuyến khích học tập"),
            ("ban hành Quy chế học bổng", "\fkhuyến khích học tập"),
            ("ban hành Quy chế học bổng.", "không lấy thêm văn bản"),
            ("ban hành Quy chế học bổng;", "không lấy thêm văn bản"),
        )):
            with self.subTest(subject=subject, following=following):
                text = f"V/v {subject}\n{following}"
                with patch.object(self.repository, "extract", return_value=(text, 1)):
                    entry = self.repository.add(
                        "scan_001.pdf", f"%PDF-1.7 single {index}".encode(),
                        metadata={"decision_number": "34/QĐ-ĐHKT"},
                    )
                self.assertEqual(entry["title"], f"Thông báo 34/QĐ-ĐHKT - {subject}")

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
