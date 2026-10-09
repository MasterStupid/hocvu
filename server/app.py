"""Small standard-library HTTP API for the HocVu AI pilot."""
from __future__ import annotations

import json
import mimetypes
import os
import re
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from core.engine import HocVuEngine, build_index
from core.documents import DocumentError, DocumentRepository
from core.settings import INDEX_JSON, SERVER_META, UI, ensure_dirs, load_config


engine: HocVuEngine | None = None
requires_api_token = False


class HocVuHandler(BaseHTTPRequestHandler):
    server_version = "HocVuAI/0.2"
    _request_times: dict[str, list[float]] = {}
    _rate_lock = threading.Lock()

    def log_message(self, fmt, *args):
        return

    def _headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-HocVu-Token")

    def _check_api_access(self) -> bool:
        if not self.path.startswith("/api/"):
            return True
        # Hosting providers call this endpoint directly and cannot attach the
        # private proxy token.  It deliberately exposes only operational
        # status, never a document, index, session, or answer.
        if urlparse(self.path).path == "/api/health":
            return True
        if requires_api_token and self.headers.get("X-HocVu-Token", "") != engine.config.api_token:
            self.respond_json({"error": "API token is required for network access."}, 401)
            return False
        now = time.monotonic()
        client = self.client_address[0]
        with self._rate_lock:
            recent = [stamp for stamp in self._request_times.get(client, []) if now - stamp < 60]
            if len(recent) >= engine.config.rate_limit_per_minute:
                self._request_times[client] = recent
                self.respond_json({"error": "Too many requests; try again in a minute."}, 429)
                return False
            recent.append(now)
            self._request_times[client] = recent
        return True

    def respond_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._headers()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._headers()
        self.end_headers()

    def _json_body(self):
        size = int(self.headers.get("Content-Length", "0"))
        if size > 1_000_000:
            raise ValueError("Request too large")
        data = json.loads(self.rfile.read(size).decode("utf-8")) if size else {}
        if not isinstance(data, dict):
            raise ValueError("JSON request body phải là một object.")
        return data

    def do_GET(self):
        if not self._check_api_access():
            return
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self.respond_json({
                "status": "ok", "documents": len(engine.list_documents()), "voice": "browser",
                "retrieval": engine.searcher.provider,
                "semantic_error": engine.searcher.semantic_error,
                "api_version": "answer-cards-1",
            })
        elif parsed.path == "/api/documents":
            self.respond_json(engine.list_documents())
        elif parsed.path.startswith("/api/documents/") and parsed.path.endswith("/text"):
            item_id = parsed.path.removeprefix("/api/documents/").removesuffix("/text").strip("/")
            try:
                self.respond_json(engine.document_text(item_id))
            except DocumentError as exc:
                self.respond_json({"error": str(exc)}, 404)
        elif parsed.path == "/api/history":
            session_id = parse_qs(parsed.query).get("session_id", [""])[0]
            self.respond_json(engine.history(session_id))
        elif parsed.path == "/api/suggestions":
            self.respond_json(engine.suggestion_topics())
        elif parsed.path.startswith("/api/"):
            self.respond_json({"error": "Not found"}, 404)
        else:
            self._serve_static(parsed.path)

    def _serve_static(self, requested: str):
        relative = "index.html" if requested in ("", "/") else requested.lstrip("/")
        root = UI.resolve()
        filepath = (root / relative).resolve()
        if root not in filepath.parents and filepath != root:
            self.send_error(403)
            return
        if not filepath.is_file():
            self.send_error(404)
            return
        data = filepath.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(str(filepath))[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self._headers()
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if not self._check_api_access():
            return
        path = urlparse(self.path).path
        if path == "/api/documents/upload":
            self._upload_document()
            return
        try:
            data = self._json_body()
        except (ValueError, json.JSONDecodeError) as exc:
            self.respond_json({"error": str(exc)}, 400)
            return
        if path == "/api/ask":
            session_id = str(data.get("session_id") or uuid.uuid4())
            response = engine.ask(
                data.get("question", ""), session_id, data.get("ref_date"),
                bool(data.get("with_audio")), use_ai=bool(data.get("use_ai")),
            )
            self.respond_json(response.to_dict())
        elif path == "/api/documents/reindex":
            self.respond_json(engine.rebuild_index())
        else:
            self.respond_json({"error": "Not found"}, 404)

    def _upload_document(self):
        content_type = self.headers.get("Content-Type", "")
        if not content_type.startswith("multipart/form-data"):
            self.respond_json({"error": "Yêu cầu phải là multipart/form-data."}, 400)
            return
        try:
            filename, content, fields = self._read_multipart_file()
            if not filename:
                raise DocumentError("Hãy chọn một tệp PDF, DOCX hoặc ảnh.")
            use_ocr = fields.get("ocr", "").strip().lower() in {"1", "true", "on", "yes"}
            metadata = {key: fields.get(key, "") for key in ("order", "decision_number", "article_clause", "document_date")}
            item = engine.add_document(filename, content, use_ocr=use_ocr, metadata=metadata)
            self.respond_json(item, 201)
        except DocumentError as exc:
            self.respond_json({"error": str(exc)}, 400)
        except Exception:
            self.respond_json({"error": "Không thể đọc tệp. Hãy kiểm tra tệp hợp lệ, không bị mã hóa và tùy chọn OCR."}, 400)

    def _read_multipart_file(self) -> tuple[str, bytes, dict[str, str]]:
        """Read one `file` form part without the removed cgi module.

        The server accepts only a single, bounded upload and does not preserve
        request headers supplied by the browser as file metadata.
        """
        content_type = self.headers.get("Content-Type", "")
        match = re.search(r'boundary=(?:"([^"]+)"|([^;\s]+))', content_type)
        if not match:
            raise DocumentError("Không tìm thấy ranh giới dữ liệu tải lên.")
        boundary = (match.group(1) or match.group(2)).encode("utf-8")
        content_length = int(self.headers.get("Content-Length", "0"))
        if not 0 < content_length <= DocumentRepository.max_bytes + 64 * 1024:
            raise DocumentError("Kích thước yêu cầu không hợp lệ hoặc vượt quá 25 MB.")
        body = self.rfile.read(content_length)
        marker = b"--" + boundary
        fields: dict[str, str] = {}
        selected: tuple[str, bytes] | None = None
        for part in body.split(marker):
            headers, separator, payload = part.partition(b"\r\n\r\n")
            if not separator:
                continue
            name_match = re.search(br'\bname="?([^";\s]+)"?', headers, flags=re.IGNORECASE)
            filename_match = re.search(br'\bfilename="?([^";\r\n]+)"?', headers, flags=re.IGNORECASE)
            if not name_match:
                continue
            # Multipart framing contributes exactly one CRLF before boundary;
            # do not use rstrip(), which could corrupt binary ZIP/PDF content.
            if payload.endswith(b"\r\n"):
                payload = payload[:-2]
            name = name_match.group(1).decode("utf-8", errors="replace")
            if filename_match and name == "file":
                selected = (filename_match.group(1).decode("utf-8", errors="replace"), payload)
            else:
                fields[name] = payload.decode("utf-8", errors="replace")
        if selected:
            return selected[0], selected[1], fields
        raise DocumentError("Không tìm thấy trường tệp trong yêu cầu tải lên.")

    def do_DELETE(self):
        if not self._check_api_access():
            return
        prefix = "/api/documents/"
        if not self.path.startswith(prefix):
            self.respond_json({"error": "Not found"}, 404)
            return
        item_id = self.path[len(prefix):].strip("/")
        if not item_id or "/" in item_id:
            self.respond_json({"error": "Invalid document id"}, 400)
            return
        try:
            engine.remove_document(item_id)
            self.respond_json({"status": "deleted"})
        except DocumentError as exc:
            self.respond_json({"error": str(exc)}, 404)


def main(host="127.0.0.1", port=8000, verbose=False, open_browser=False):
    global engine, requires_api_token
    config = load_config()
    requires_api_token = host not in {"127.0.0.1", "localhost", "::1"}
    if requires_api_token and not config.api_token:
        raise RuntimeError("Khi mở server ra mạng, hãy đặt HV_API_TOKEN để bảo vệ tài liệu và API.")
    ensure_dirs()
    if not INDEX_JSON.exists():
        _, searcher = build_index(config, return_searcher=True)
        engine = HocVuEngine(config, searcher)
    else:
        engine = HocVuEngine.load(config, INDEX_JSON)
    server = ThreadingHTTPServer((host, port), HocVuHandler)
    SERVER_META.write_text(json.dumps({"pid": os.getpid(), "port": port}), encoding="utf-8")
    url = f"http://{host}:{port}"
    print(f"HocVu AI is running at {url}")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        SERVER_META.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
