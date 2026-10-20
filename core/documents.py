"""Local PDF/DOCX ingestion and metadata management for the knowledge base."""
from __future__ import annotations

import json
import io
import hashlib
import re
import shutil
import uuid
import zipfile
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from xml.etree import ElementTree

from .models import Article, Clause, Regulation


class DocumentError(ValueError):
    pass


class DocumentNotFoundError(DocumentError):
    pass


class DocumentRepository:
    allowed_extensions = {".pdf", ".docx", ".png", ".jpg", ".jpeg", ".webp"}
    image_extensions = {".png", ".jpg", ".jpeg", ".webp"}
    max_bytes = 25 * 1024 * 1024
    extraction_version = 4
    # Bump whenever _make_articles (or anything else that changes article
    # headings/clauses of uploaded documents) changes its output. The saved
    # search index records this, and the server rebuilds a stale index at
    # startup so earlier uploads pick up the new citations automatically.
    article_version = 1

    @classmethod
    def article_build_version(cls) -> str:
        """Identifies how uploaded documents are turned into articles.

        Extraction changes alter the text articles are built from, so both
        versions are part of the identifier stored in the search index.
        """
        return f"extraction-{cls.extraction_version}.articles-{cls.article_version}"

    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.extracted_root = self.root / "extracted"
        self.extracted_root.mkdir(parents=True, exist_ok=True)
        self.manifest = self.root / "manifest.json"
        self.manifest_backup = self.root / "manifest.json.bak"

    def _extracted_path(self, item_id: str) -> Path:
        """Location of the plain-text representation used for indexing."""
        return self.extracted_root / f"{item_id}.txt"

    def _read_manifest(self) -> list[dict]:
        if not self.manifest.exists():
            return []
        try:
            entries = json.loads(self.manifest.read_text(encoding="utf-8"))
            if not isinstance(entries, list):
                raise json.JSONDecodeError("Manifest must be a list", "", 0)
            return entries
        except json.JSONDecodeError as exc:
            if self.manifest_backup.exists():
                try:
                    entries = json.loads(self.manifest_backup.read_text(encoding="utf-8"))
                    if not isinstance(entries, list):
                        raise json.JSONDecodeError("Manifest backup must be a list", "", 0)
                except json.JSONDecodeError:
                    entries = None
                if entries is not None:
                    # Repair the active copy from the last known-good atomic backup.
                    temp = self.manifest.with_suffix(".restore.tmp")
                    temp.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
                    temp.replace(self.manifest)
                    return entries
            raise DocumentError("Danh mục tài liệu bị lỗi và không có bản sao lưu hợp lệ.") from exc

    def _write_manifest(self, entries: list[dict]) -> None:
        temp = self.manifest.with_suffix(".tmp")
        temp.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
        if self.manifest.exists():
            shutil.copy2(self.manifest, self.manifest_backup)
        temp.replace(self.manifest)

    def _content_hash(self, entry: dict) -> str:
        existing = entry.get("sha256")
        if existing:
            return str(existing)
        stored = self.root / str(entry.get("stored_name", ""))
        if not stored.is_file():
            return ""
        digest = hashlib.sha256(stored.read_bytes()).hexdigest()
        entry["sha256"] = digest
        return digest

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
                document_date = date.fromisoformat(document_date).isoformat()
            except ValueError as exc:
                raise DocumentError("Ngày áp dụng phải là ngày hợp lệ theo định dạng YYYY-MM-DD.") from exc
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
        content_hash = hashlib.sha256(content).hexdigest()
        entries = self._read_manifest()
        for existing in entries:
            if self._content_hash(existing) == content_hash:
                raise DocumentError(f"Tệp trùng với tài liệu đã tải lên: {existing.get('filename', 'không rõ tên')}.")
        item_id = uuid.uuid4().hex
        metadata = self._metadata(metadata)
        safe_name = self._safe_name(filename)
        path = self.root / f"{item_id}{suffix}"
        path.write_bytes(content)
        try:
            text, pages = self.extract(path, use_ocr=use_ocr)
            if len(text.strip()) < 20:
                raise DocumentError("Không trích xuất được đủ nội dung văn bản từ tệp.")
            if not metadata.get("document_date"):
                date_m = re.search(
                    r"\bngày\s+(\d{1,2})\s+tháng\s+(\d{1,2})\s+năm\s+(\d{4})",
                    text, re.IGNORECASE,
                )
                if date_m:
                    day, month, year = map(int, date_m.groups())
                    try:
                        metadata["document_date"] = date(year, month, day).isoformat()
                    except ValueError as exc:
                        raise DocumentError(
                            f"Ngày tự nhận diện {day:02d}/{month:02d}/{year:04d} không hợp lệ. "
                            "Hãy nhập ngày áp dụng chính xác (YYYY-MM-DD) khi tải lên."
                        ) from exc
            # Keep an extracted Unicode text copy. The search index is built
            # from this representation, never directly from a page layout.
            self._extracted_path(item_id).write_text(text, encoding="utf-8")
        except Exception:
            path.unlink(missing_ok=True)
            self._extracted_path(item_id).unlink(missing_ok=True)
            raise
        title = Path(safe_name).stem
        if not metadata.get("decision_number"):
            # Unicode-aware: Vietnamese decision numbers use letters such as
            # "Đ" (12/QĐ-ĐH, 05/2026/TT-BGDĐT) that an ASCII class truncates.
            num_m = re.search(r"\b(?:Số hiệu|Số)\s*:\s*([0-9]+(?:/[\w-]+)+)", text, re.IGNORECASE)
            if num_m:
                metadata["decision_number"] = num_m.group(1).strip()
        explicit_subject = self._explicit_subject(text)
        if metadata.get("decision_number") and explicit_subject:
            title = f"Thông báo {metadata['decision_number']} - {explicit_subject}"[:150]
        elif metadata.get("decision_number"):
            # Without an explicit subject line, still name the topic: use the
            # first meaningful heading, else the filename. The decision number
            # stays in the title prefix and in metadata (used for version).
            subject = self._subject_from_text(text, metadata["decision_number"]) or self._subject_from_filename(safe_name)
            title = f"Văn bản {metadata['decision_number']}"
            if subject:
                title = f"{title} - {subject}"[:150]

        entry = {
            "id": item_id,
            "rid": f"UPL-{item_id[:8].upper()}",
            "filename": safe_name,
            "stored_name": path.name,
            "title": title,
            "format": suffix[1:].upper(),
            "size": len(content),
            "pages": pages,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
            "status": "ready",
            "ocr": bool(use_ocr),
            "extraction_version": self.extraction_version,
            "sha256": content_hash,
            **metadata,
        }
        entries.append(entry)
        self._write_manifest(entries)
        return entry

    @staticmethod
    def _explicit_subject(text: str) -> str:
        """Join likely soft wraps, not the following administrative body.

        Continuations must be adjacent lowercase fragments. Blank lines,
        capitalized text, markup, lists, section labels and common body/preamble
        openings end the subject. Sentence-ending punctuation ends it too.
        Ambiguous capitalized wraps are deliberately left alone rather than
        risking pulling a body paragraph into a single-line subject.
        """
        match = re.search(
            r"(?:\b(?:Tiêu đề|Về việc):[ \t]*"
            # DOCX heading styles become Markdown during extraction. Allow
            # that marker only at line start, not before subject words in body.
            r"|^[ \t]*(?:#{1,6}[ \t]+)?(?:V/v|Về việc)(?:[ \t]*:[ \t]*|[ \t]+))([^\r\n]+)",
            text,
            re.IGNORECASE | re.MULTILINE,
        )
        if not match:
            return ""
        subject = match.group(1).strip()
        # Do not skip a blank line (or a page break) while looking for wraps.
        remainder = text[match.end():]
        remainder = re.sub(r"^(?:\r\n|\r|\n)", "", remainder, count=1)
        body_start = re.compile(
            r"^(?:(?:điều|chương|mục|phần|khoản)\s+(?:\d+|[ivxlcdm]+)\b"
            r"|(?:căn cứ|xét đề nghị|quyết định|kính gửi|nơi nhận|nội dung"
            r"|sinh viên|nhà trường|đề nghị|yêu cầu|thực hiện|hiệu trưởng"
            r"|trường|phòng|các đơn vị|đối tượng|thời gian|số|tiêu đề|về việc)\b"
            r"|v/v\b)",
            re.IGNORECASE,
        )
        for raw_line in remainder.splitlines():
            line = raw_line.strip()
            if (
                not line
                or subject.endswith((".", ";", "!", "?", ":"))
                or not line[0].islower()
                or re.match(r"^[a-zđ][.)]\s", line)
                or body_start.match(line)
            ):
                break
            subject += " " + line
            # add() already caps the complete title at 150 characters.
            if len(subject) >= 150:
                break
        return subject

    # Headings that appear at the top of most Vietnamese administrative
    # documents but say nothing about the document's subject.
    _boilerplate_heading = re.compile(
        r"^(?:cộng hòa xã hội chủ nghĩa việt nam|độc lập\s*-\s*tự do\s*-\s*hạnh phúc"
        r"|quyết định|thông báo|công văn|thông tư|nghị định|hướng dẫn|kế hoạch|tờ trình"
        r"|mục lục|mở đầu|căn cứ\b.*)$",
        re.IGNORECASE,
    )

    @classmethod
    def _subject_from_text(cls, text: str, decision_number: str) -> str:
        """First markdown heading that names the document's subject."""
        for line in text.splitlines():
            match = re.match(r"^#{1,6}\s+(.+)$", line.strip())
            if not match:
                continue
            heading = re.sub(r"^[\*\s]+|[\*\s:]+$", "", match.group(1))
            heading = re.sub(r"\s+", " ", heading).strip()
            if len(heading) < 3 or cls._is_table_of_contents_line(heading):
                continue
            if decision_number and decision_number.lower() in heading.lower():
                continue
            if cls._boilerplate_heading.match(heading):
                continue
            return heading[:120]
        return ""

    @staticmethod
    def _subject_from_filename(safe_name: str) -> str:
        """Readable subject from a filename stem, ignoring meaningless names."""
        stem = re.sub(r"[_\s]+", " ", Path(safe_name).stem).strip(" -.")
        if len(stem) < 3 or not re.search(r"[^\W\d_]", stem):
            return ""
        if re.fullmatch(r"[0-9a-f]{16,}", stem, re.IGNORECASE):
            return ""
        # Scanner/camera/default names ("scan_001", "IMG_2041", "Document (3)",
        # "tai_lieu") describe the file, not the document's subject.
        generic = (r"(?:scan(?:ned)?|img|image|photo|picture|dsc|pxl|cam|camera|document|doc|file|untitled"
                   r"|new document|tai lieu|van ban|tài liệu|văn bản|ảnh|anh)")
        if re.fullmatch(rf"{generic}(?:[\s\-.()]*\d+)*[\s\-.()]*", stem, re.IGNORECASE):
            return ""
        return stem[:120]

    @contextmanager
    def change_date(self, item_id: str, document_date: str):
        """Persist a date-only edit; undo it if the caller's reindex fails."""
        value = self._metadata({"document_date": document_date})["document_date"]
        if not value:
            raise DocumentError("Hãy nhập ngày áp dụng hợp lệ (YYYY-MM-DD).")
        entries = self._read_manifest()
        selected = next((item for item in entries if item["id"] == item_id), None)
        if selected is None:
            raise DocumentNotFoundError("Không tìm thấy tài liệu.")
        had_date = "document_date" in selected
        previous = selected.get("document_date")
        selected["document_date"] = value
        self._write_manifest(entries)
        try:
            yield dict(selected)
        except Exception:
            # Restore only this field, preserving any unrelated metadata edits.
            current = self._read_manifest()
            entry = next((item for item in current if item["id"] == item_id), None)
            if entry is not None and entry.get("document_date") == value:
                if had_date:
                    entry["document_date"] = previous
                else:
                    entry.pop("document_date", None)
                self._write_manifest(current)
            raise

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
        total_text_len = sum(len(p.strip()) for p in pages)
        is_scanned = total_text_len < 100 or use_ocr
        if is_scanned:
            # 1. Ưu tiên VLM (Vision-Language Model) thông minh để khử nhiễu và đọc chính xác link/mã QR
            vlm_text = self._extract_pdf_vlm(path)
            if vlm_text:
                return vlm_text, len(pages)
            # 2. Fallback sang Tesseract OCR cục bộ
            ocr_text = self._extract_pdf_ocr(path, pages)
            for index, text in enumerate(ocr_text):
                if text:
                    pages[index] = f"{pages[index]}\n{text}".strip()
        return "\n".join(pages), len(pages)

    def _extract_pdf_vlm(self, path: Path) -> str:
        """Trích xuất và tóm tắt thông báo bằng mô hình VLM (Gemini Vision) với độ chính xác cao nhất."""
        try:
            from .settings import load_config
            from .llm import GroundedLLM
            import fitz
            import base64
            import json
            import urllib.request

            cfg = load_config()
            if not cfg.gemini_key:
                return ""

            doc = fitz.open(str(path))
            parts = [{
                "text": (
                    "Bạn là chuyên gia số hóa văn bản giáo dục đại học. Hãy phân tích toàn bộ các trang thông báo sau và thực hiện 2 việc:\n"
                    "1. Tạo [TỔNG QUAN ĐIỀU HÀNH & HƯỚNG DẪN SINH VIÊN] ở đầu (gồm: Số hiệu, Ngày, Tiêu đề, Đối tượng áp dụng, Yêu cầu thông tin nộp, "
                    "HẠN CHÓT HOÀN THÀNH, ĐƯỜNG DẪN LINK BIỂU MẪU CHÍNH XÁC từng chữ/số, CÁN BỘ VÀ SỐ ĐIỆN THOẠI LIÊN HỆ HỖ TRỢ).\n"
                    "2. Trích xuất TOÀN VĂN SẠCH CỦA CÁC MỤC (I, II, III, IV...) theo định dạng Markdown. Bỏ qua nhiễu đốm ảnh của mã QR code và con dấu đỏ."
                )
            }]
            for page in doc:
                pix = page.get_pixmap(dpi=150)
                img_bytes = pix.tobytes("jpeg")
                parts.append({
                    "inlineData": {
                        "mimeType": "image/jpeg",
                        "data": base64.b64encode(img_bytes).decode("utf-8")
                    }
                })
            doc.close()

            endpoint = GroundedLLM._gemini_endpoint(cfg.gemini_url, cfg.gemini_model)
            payload = {
                "contents": [{"parts": parts}],
                "generationConfig": {"maxOutputTokens": 3500, "temperature": 0.1}
            }
            req = urllib.request.Request(
                endpoint,
                data=json.dumps(payload).encode("utf-8"),
                headers={"x-goog-api-key": cfg.gemini_key, "Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=45) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            extracted = GroundedLLM._gemini_output_text(body)
            return extracted.strip()
        except Exception:
            return ""

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
        if re.match(r"^#{1,6}\s+", compact):
            return True
        if re.match(r"^(CHƯƠNG|PHẦN|MỞ ĐẦU|KẾT LUẬN|TÀI LIỆU THAM KHẢO|PHỤ LỤC)\b", compact, re.IGNORECASE):
            return True
        if re.match(r"^(?:[IVXLCDM]+\.|\d+(?:\.\d+){0,4}\.?)\s+[A-ZÀ-Ỹ]", compact):
            return True
        if re.match(r"^\*\*(?:[IVXLCDM]+\.|\d+\.)\s+", compact):
            return True
        return False

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
                if len(current) + len(paragraph) + 1 > 700 and current:
                    clauses.append(Clause(str(len(clauses) + 1), current))
                    current = paragraph
                else:
                    current = f"{current} {paragraph}".strip()
            if current:
                clauses.append(Clause(str(len(clauses) + 1), current))
            if clauses:
                # An article heading names only its section. The document
                # title (and its decision number) is regulation metadata that
                # citations, the LLM context and the index already carry
                # separately, so it is not repeated here. Text before the
                # first section heading falls back to the document title.
                clean_heading = re.sub(r"^[\*#\s]+|\*+$", "", heading).strip() or document_title
                articles.append(Article(f"Mục {len(articles) + 1}", clean_heading, clauses))
            buffer.clear()

        for paragraph in paragraphs:
            if cls._is_heading(paragraph):
                flush()
                inline_bold = re.match(r"^\*\*([^*]+)\*\*[:\s]*(.*)$", paragraph)
                if inline_bold:
                    heading = inline_bold.group(1).strip()
                    remainder = inline_bold.group(2).strip()
                    if remainder:
                        buffer.append(f"**{heading}:** {remainder}")
                else:
                    raw_h = re.sub(r"^#{1,6}\s+", "", paragraph)
                    heading = re.sub(r"^\*\s+", "", raw_h)[:120].strip()
                    if not re.match(r"^#{1,6}\s+", paragraph):
                        buffer.append(paragraph)
            else:
                buffer.append(paragraph)
        flush()
        return articles or [Article("Nội dung", document_title, [Clause("1", text[:6000])])]
