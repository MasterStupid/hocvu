"""Local PDF/DOCX ingestion and metadata management for the knowledge base."""
from __future__ import annotations

import json
import io
import re
import shutil
import uuid
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path
from xml.etree import ElementTree

from .models import Article, Clause, Regulation


class DocumentError(ValueError):
    pass


class DocumentRepository:
    allowed_extensions = {".pdf", ".docx", ".png", ".jpg", ".jpeg", ".webp"}
    image_extensions = {".png", ".jpg", ".jpeg", ".webp"}
    max_bytes = 25 * 1024 * 1024
    extraction_version = 4

    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.extracted_root = self.root / "extracted"
        self.extracted_root.mkdir(parents=True, exist_ok=True)
        self.manifest = self.root / "manifest.json"

    def _extracted_path(self, item_id: str) -> Path:
        """Location of the plain-text representation used for indexing."""
        return self.extracted_root / f"{item_id}.txt"

    def _read_manifest(self) -> list[dict]:
        if not self.manifest.exists():
            return []
        try:
            return json.loads(self.manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise DocumentError("Danh mục tài liệu bị lỗi; không thể đọc an toàn.") from exc

    def _write_manifest(self, entries: list[dict]) -> None:
        temp = self.manifest.with_suffix(".tmp")
        temp.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.manifest)

    @staticmethod
    def _safe_name(name: str) -> str:
        cleaned = re.sub(r"[^\w.() -]", "_", Path(name).name, flags=re.UNICODE).strip(" .")
        return cleaned[:120] or "tai_lieu"

    def list(self) -> list[dict]:
        def key(item: dict):
            try:
                return int(item.get("order", 999999))
            except (TypeError, ValueError):
                return 999999
        return sorted(self._read_manifest(), key=key)

    @staticmethod
    def _metadata(raw: dict | None) -> dict:
        raw = raw or {}
        try:
            order = int(str(raw.get("order", "") or 0))
        except ValueError as exc:
            raise DocumentError("Số thứ tự phải là số nguyên dương.") from exc
        if order < 0:
            raise DocumentError("Số thứ tự không được âm.")
        document_date = str(raw.get("document_date", "") or "").strip()
        if document_date:
            try:
                date.fromisoformat(document_date)
            except ValueError as exc:
                raise DocumentError("Ngày áp dụng cần theo định dạng YYYY-MM-DD.") from exc
        return {
            "order": order or None,
            "decision_number": str(raw.get("decision_number", "") or "").strip()[:100],
            "article_clause": str(raw.get("article_clause", "") or "").strip()[:100],
            "document_date": document_date or None,
        }

    def add(self, filename: str, content: bytes, use_ocr: bool = False, metadata: dict | None = None) -> dict:
        suffix = Path(filename).suffix.lower()
        if suffix not in self.allowed_extensions:
            raise DocumentError("Chỉ hỗ trợ PDF, DOCX hoặc ảnh PNG/JPG/WEBP khi bật OCR.")
        if suffix in self.image_extensions and not use_ocr:
            raise DocumentError("Tệp ảnh cần bật tùy chọn OCR trước khi tải lên.")
        if not content or len(content) > self.max_bytes:
            raise DocumentError("Tệp phải có dung lượng từ 1 byte đến 25 MB.")
        if suffix == ".pdf" and not content.lstrip().startswith(b"%PDF-"):
            raise DocumentError("Tệp không phải PDF hợp lệ.")
        if suffix == ".docx" and content[:2] != b"PK":
            raise DocumentError("Tệp không phải DOCX hợp lệ.")
        item_id = uuid.uuid4().hex
        metadata = self._metadata(metadata)
        safe_name = self._safe_name(filename)
        path = self.root / f"{item_id}{suffix}"
        path.write_bytes(content)
        try:
            text, pages = self.extract(path, use_ocr=use_ocr)
            if len(text.strip()) < 20:
                raise DocumentError("Không trích xuất được đủ nội dung văn bản từ tệp.")
            # Keep an extracted Unicode text copy. The search index is built
            # from this representation, never directly from a page layout.
            self._extracted_path(item_id).write_text(text, encoding="utf-8")
        except Exception:
            path.unlink(missing_ok=True)
            self._extracted_path(item_id).unlink(missing_ok=True)
            raise
        entry = {
            "id": item_id,
            "rid": f"UPL-{item_id[:8].upper()}",
            "filename": safe_name,
            "stored_name": path.name,
            "title": Path(safe_name).stem,
            "format": suffix[1:].upper(),
            "size": len(content),
            "pages": pages,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
            "status": "ready",
            "ocr": bool(use_ocr),
            "extraction_version": self.extraction_version,
            **metadata,
        }
        entries = self._read_manifest()
        entries.append(entry)
        self._write_manifest(entries)
        return entry

    def remove(self, item_id: str) -> None:
        entries = self._read_manifest()
        selected = next((item for item in entries if item["id"] == item_id), None)
        if not selected:
            raise DocumentError("Không tìm thấy tài liệu.")
        (self.root / selected["stored_name"]).unlink(missing_ok=True)
        self._extracted_path(item_id).unlink(missing_ok=True)
        self._write_manifest([item for item in entries if item["id"] != item_id])

    def get_text(self, item_id: str) -> dict:
        entry = next((item for item in self._read_manifest() if item["id"] == item_id), None)
        if not entry:
            raise DocumentError("Không tìm thấy tài liệu.")
        extracted_path = self._extracted_path(item_id)
        if extracted_path.exists():
            text = extracted_path.read_text(encoding="utf-8")
        else:
            text, _ = self.extract(self.root / entry["stored_name"], use_ocr=entry.get("ocr", False))
            extracted_path.write_text(text, encoding="utf-8")
        return {"id": item_id, "title": entry["title"], "text": text, "chunk_count": None}

    def extract(self, path: Path, use_ocr: bool = False) -> tuple[str, int]:
        if path.suffix.lower() == ".pdf":
            return self._extract_pdf(path, use_ocr)
        if path.suffix.lower() in self.image_extensions:
            if not use_ocr:
                raise DocumentError("Hãy bật OCR để đọc nội dung từ tệp ảnh.")
            return self._extract_image_ocr(path), 1
        return self._extract_docx(path, use_ocr), 1

    @staticmethod
    def _pdf_reader(path: Path):
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise DocumentError("Để đọc PDF, hãy cài pypdf bằng lệnh: python -m pip install -r requirements.txt") from exc
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            raise DocumentError("PDF được mã hóa nên chưa thể lập chỉ mục.")
        return reader

    def _extract_pdf(self, path: Path, use_ocr: bool) -> tuple[str, int]:
        reader = self._pdf_reader(path)
        pages = [page.extract_text() or "" for page in reader.pages]
        if use_ocr:
            ocr_text = self._extract_pdf_ocr(path, pages)
            for index, text in enumerate(ocr_text):
                if text:
                    pages[index] = f"{pages[index]}\n{text}".strip()
        return "\n".join(pages), len(pages)

    def _extract_pdf_ocr(self, path: Path, page_texts: list[str]) -> list[str]:
        """OCR only pages without a usable PDF text layer."""
        try:
            import fitz
        except ImportError as exc:
            raise DocumentError("OCR PDF cần PyMuPDF. Hãy cài lại requirements.txt.") from exc
        document = fitz.open(str(path))
        results = ["" for _ in page_texts]
        try:
            for index, page in enumerate(document):
                if len(page_texts[index].strip()) >= 40:
                    continue
                pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                results[index] = self._ocr_pil_image_from_bytes(pixmap.tobytes("png"))
        finally:
            document.close()
        return results

    @staticmethod
    def _configure_ocr():
        try:
            import pytesseract
        except ImportError as exc:
            raise DocumentError("OCR chưa được cài. Hãy cài các phụ thuộc OCR theo hướng dẫn quản trị.") from exc
        executable = shutil.which("tesseract")
        if not executable:
            for candidate in (Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"), Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe")):
                if candidate.exists():
                    executable = str(candidate)
                    break
        if not executable:
            raise DocumentError("Không tìm thấy Tesseract OCR trên máy chủ.")
        pytesseract.pytesseract.tesseract_cmd = executable
        if "vie" not in pytesseract.get_languages(config=""):
            raise DocumentError("Tesseract chưa có gói tiếng Việt (vie).")
        return pytesseract

    def _ocr_pil_image_from_bytes(self, content: bytes) -> str:
        try:
            from PIL import Image
            with Image.open(io.BytesIO(content)) as image:
                return self._ocr_pil_image(image)
        except DocumentError:
            raise
        except Exception as exc:
            raise DocumentError("Không thể mở ảnh để OCR.") from exc

    def _ocr_pil_image(self, image) -> str:
        try:
            from PIL import Image, ImageOps
            pytesseract = self._configure_ocr()
            prepared = ImageOps.autocontrast(ImageOps.grayscale(image))
            if max(prepared.size) < 2400:
                prepared = prepared.resize((prepared.width * 2, prepared.height * 2), Image.Resampling.LANCZOS)
            return pytesseract.image_to_string(prepared, lang="vie+eng", config="--oem 1 --psm 6")
        except DocumentError:
            raise
        except Exception as exc:
            raise DocumentError("Không thể OCR ảnh này. Hãy dùng ảnh rõ nét, đúng chiều và không bị mờ.") from exc

    def _extract_image_ocr(self, path: Path) -> str:
        """Read a Vietnamese/English image locally through Tesseract OCR."""
        return self._ocr_pil_image_from_bytes(path.read_bytes())

    def _extract_docx(self, path: Path, use_ocr: bool = False) -> str:
        """Extract DOCX text and, optionally, OCR embedded images.

        A Word document's table of contents is made from ordinary-looking
        paragraphs, so plain XML text extraction accidentally indexed it as
        document content. Heading styles are reliable metadata: retain them
        as lightweight markers and skip generated TOC styles completely.
        """
        try:
            with zipfile.ZipFile(path) as archive:
                xml = archive.read("word/document.xml")
                embedded_images = [archive.read(name) for name in archive.namelist() if use_ocr and name.startswith("word/media/")]
        except (KeyError, zipfile.BadZipFile) as exc:
            raise DocumentError("Tệp DOCX không hợp lệ hoặc bị hỏng.") from exc
        root = ElementTree.fromstring(xml)
        namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        value_attr = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val"
        blocks = []
        for paragraph in root.findall(".//w:p", namespace):
            text = "".join(node.text or "" for node in paragraph.findall(".//w:t", namespace)).strip()
            style_node = paragraph.find("./w:pPr/w:pStyle", namespace)
            style = (style_node.get(value_attr, "") if style_node is not None else "").lower()
            if not text or style.startswith("toc"):
                continue
            heading = re.fullmatch(r"heading([1-6])", style)
            blocks.append(f"{'#' * int(heading.group(1))} {text}" if heading else text)
        for number, image in enumerate(embedded_images, start=1):
            recognized = self._ocr_pil_image_from_bytes(image).strip()
            if recognized:
                blocks.append(f"## Nội dung ảnh OCR {number}\n{recognized}")
        return "\n".join(blocks)

    def regulations(self) -> list[Regulation]:
        regulations = []
        entries = self.list()
        upgraded = False
        for entry in entries:
            extracted_path = self._extracted_path(entry["id"])
            if extracted_path.exists() and entry.get("extraction_version") == self.extraction_version:
                text = extracted_path.read_text(encoding="utf-8")
            else:
                # Documents uploaded before a parser improvement are upgraded
                # automatically on their next reindex.
                text, _ = self.extract(self.root / entry["stored_name"], use_ocr=entry.get("ocr", False))
                extracted_path.write_text(text, encoding="utf-8")
                entry["extraction_version"] = self.extraction_version
                upgraded = True
            articles = self._make_articles(text, entry["title"])
            decision = entry.get("decision_number")
            regulations.append(Regulation(
                rid=entry["rid"], title=entry["title"], category="Tài liệu tải lên",
                version=f"Quyết định {decision}" if decision else "Tải lên",
                # Preserve a stable fallback for documents without an entered
                # effective date; reindexing must not change their validity.
                valid_from=entry.get("document_date") or entry["uploaded_at"][:10], valid_until=None,
                issuer="Người quản lý hệ thống", articles=articles,
            ))
        if upgraded:
            self._write_manifest(entries)
        return regulations

    @staticmethod
    def _is_heading(text: str) -> bool:
        compact = re.sub(r"\s+", " ", text).strip()
        return bool(re.match(r"^#{1,6}\s+", compact) or re.match(r"^(CHƯƠNG|PHẦN|MỞ ĐẦU|KẾT LUẬN|TÀI LIỆU THAM KHẢO|PHỤ LỤC)\b", compact, re.IGNORECASE) or re.match(r"^\d+(?:\.\d+){0,4}\.?\s+", compact))

    @staticmethod
    def _is_table_of_contents_line(text: str) -> bool:
        compact = re.sub(r"\s+", " ", text).strip()
        # Do not discard an ordinary numbered line just because it ends in a
        # number. Only dot leaders are reliable evidence of a generated TOC.
        return bool(len(compact) < 240 and re.search(r"\.{3,}\s*\d{1,3}$", compact))

    @classmethod
    def _make_articles(cls, text: str, document_title: str) -> list[Article]:
        paragraphs = [re.sub(r"\s+", " ", part).strip() for part in text.splitlines()]
        paragraphs = [part for part in paragraphs if part and not cls._is_table_of_contents_line(part)]
        articles: list[Article] = []
        heading = document_title
        buffer: list[str] = []

        def flush() -> None:
            if not buffer:
                return
            clauses, current = [], ""
            for paragraph in buffer:
                if len(current) + len(paragraph) + 1 > 2200 and current:
                    clauses.append(Clause(str(len(clauses) + 1), current))
                    current = paragraph
                else:
                    current = f"{current} {paragraph}".strip()
            if current:
                clauses.append(Clause(str(len(clauses) + 1), current))
            if clauses:
                articles.append(Article(f"Mục {len(articles) + 1}", heading, clauses))
            buffer.clear()

        for paragraph in paragraphs:
            if cls._is_heading(paragraph):
                flush()
                heading = re.sub(r"^#{1,6}\s+", "", paragraph)[:180]
            else:
                buffer.append(paragraph)
        flush()
        return articles or [Article("Nội dung", document_title, [Clause("1", text[:6000])])]
