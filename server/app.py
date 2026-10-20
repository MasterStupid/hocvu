"""FastAPI RESTful web service for HocVu AI with Swagger UI and Edge-TTS support."""
from __future__ import annotations

import io
import base64
import binascii
import json
import os
import re
import secrets
import threading
import uuid
import webbrowser
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

import uvicorn
import anyio
from fastapi import FastAPI, HTTPException, Request, Response, UploadFile, File, Form, Query, status
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from core.engine import HocVuEngine
from core.session import SessionClosedError, validate_session_id
from core.documents import DocumentError, DocumentNotFoundError, DocumentRepository
from core.settings import AUD, INDEX_JSON, SERVER_META, UI, ensure_dirs, load_config
from core.voice import VoiceManager, clean_text_for_tts, DEFAULT_VOICE, DEFAULT_RATE, RATE_PATTERN, MALE_VOICE
from server.security import SlidingWindowLimiter, client_address, parse_trusted_proxies


# ── Global Engine & Voice State ──────────────────────────────────────────────
engine: HocVuEngine | None = None
_engine_lock = threading.Lock()
_voice_lock = threading.Lock()
# Offloaded writers must not race the manifest's read/modify/write cycle.
# Wait asynchronously, before reading upload bytes or occupying a worker.
_document_write_lock = anyio.Lock()
voice_manager: VoiceManager | None = None
requires_api_token = True
config = load_config()
browser_auth_enabled = os.environ.get("HV_BROWSER_AUTH", "0") == "1"
trusted_proxies = parse_trusted_proxies(os.environ.get("HV_TRUSTED_PROXIES", "127.0.0.1,::1"))


def parse_trusted_origins(value: str) -> frozenset[str]:
    """Parse exact browser origins allowed to make proxied API changes."""
    origins = set()
    for raw in value.split(","):
        raw = raw.strip()
        if not raw:
            continue
        parts = urlsplit(raw)
        if (
            parts.scheme not in {"http", "https"}
            or not parts.netloc
            or "*" in parts.netloc
            or parts.username
            or parts.password
            or parts.path not in {"", "/"}
            or parts.query
            or parts.fragment
        ):
            raise RuntimeError(
                "HV_TRUSTED_ORIGINS phải là danh sách origin đầy đủ, ví dụ https://hocvu.netlify.app"
            )
        origins.add(f"{parts.scheme}://{parts.netloc}".lower())
    return frozenset(origins)


trusted_origins = parse_trusted_origins(os.environ.get("HV_TRUSTED_ORIGINS", ""))


def valid_browser_credentials(authorization: str) -> bool:
    """Accept a browser's native HTTP Basic login without exposing the API token."""
    if not config.api_token:
        return False
    try:
        scheme, encoded = authorization.split(" ", 1)
        if scheme.lower() != "basic":
            return False
        username, password = base64.b64decode(encoded, validate=True).split(b":", 1)
        return (
            secrets.compare_digest(username, b"hocvu")
            and secrets.compare_digest(password, config.api_token.encode("utf-8"))
        )
    except (ValueError, binascii.Error):
        return False


def get_engine() -> HocVuEngine:
    global engine
    if engine is None:
        with _engine_lock:
            if engine is None:
                ensure_dirs()
                # Refresh the index once, even during concurrent first requests.
                engine = HocVuEngine.load_or_build(config, INDEX_JSON)
    return engine


def get_voice_manager() -> VoiceManager:
    global voice_manager
    if voice_manager is None:
        with _voice_lock:
            if voice_manager is None:
                voice_manager = VoiceManager(config=config, audio_dir=AUD)
    return voice_manager


def _call_engine(method: str, *args, **kwargs):
    """Keep lazy model initialization and the entire operation off the loop."""
    return getattr(get_engine(), method)(*args, **kwargs)


async def _mutate_documents(method: str, *args, **kwargs):
    async with _document_write_lock:
        return await run_in_threadpool(_call_engine, method, *args, **kwargs)


# ── Pydantic Request / Response Models ───────────────────────────────────────
class AskRequest(BaseModel):
    question: str = Field(..., max_length=4000, description="Câu hỏi quy chế của sinh viên (tối đa 4000 ký tự)")
    session_id: Optional[str] = Field(None, description="Mã định danh phiên hội thoại")
    ref_date: Optional[str] = Field(None, description="Ngày tra cứu hiệu lực văn bản (YYYY-MM-DD)")
    with_audio: Optional[bool] = Field(False, description="Yêu cầu sinh kèm URL âm thanh phản hồi")
    use_ai: Optional[bool] = Field(False, description="Bật Google Gemini diễn đạt lại câu trả lời")


class TTSRequest(BaseModel):
    text: str = Field(..., description="Văn bản cần đọc")
    voice: Optional[str] = Field(DEFAULT_VOICE, description="Tên giọng đọc (vi-VN-HoaiMyNeural hoặc vi-VN-NamMinhNeural)")
    rate: Optional[str] = Field(DEFAULT_RATE, pattern=RATE_PATTERN, max_length=12, description="Tốc độ đọc, ví dụ: +0%, +10%, -10%")


class DocumentDateRequest(BaseModel):
    model_config = {"extra": "forbid"}
    document_date: str = Field(..., min_length=1, max_length=32, description="Ngày áp dụng mới, định dạng YYYY-MM-DD")


# ── Khởi tạo Ứng dụng FastAPI ────────────────────────────────────────────────
app = FastAPI(
    title="HocVu AI API",
    description="Hệ thống Trợ lý ảo tư vấn Quy chế Đào tạo Sinh viên (RAG & Voice Assistant) - ĐH Hải Phòng",
    version="1.0.0",
    docs_url="/docs" if os.environ.get("HV_API_DOCS", "0") == "1" else None,
    redoc_url="/redoc" if os.environ.get("HV_API_DOCS", "0") == "1" else None,
    openapi_url="/openapi.json" if os.environ.get("HV_API_DOCS", "0") == "1" else None,
)

# The bundled UI and Netlify's API proxy are same-origin. Do not enable
# credentialed cross-origin browser access to the editable regulation corpus.

request_limiter = SlidingWindowLimiter()


@app.exception_handler(SessionClosedError)
async def session_closed_handler(request: Request, exc: SessionClosedError):
    return JSONResponse(
        status_code=410,
        content={"detail": str(exc), "code": "session_closed", "session_id": exc.session_id},
        headers={"Cache-Control": "no-store"},
    )


@app.middleware("http")
async def rate_limit_and_auth_middleware(request: Request, call_next):
    path = request.url.path
    # Count invalid credentials too, including Basic attempts against UI pages.
    # The health probe stays public and does not consume a user's allowance.
    protected_api = path.startswith("/api/") and path != "/api/health"
    if protected_api or (browser_auth_enabled and path != "/api/health"):
        retry_after = request_limiter.consume(
            client_address(request, trusted_proxies), config.rate_limit_per_minute,
        )
        if retry_after:
            return JSONResponse(
                status_code=429,
                content={"error": "Too many requests; try again later."},
                headers={"Retry-After": str(retry_after)},
            )

    # Opt-in browser authentication for a single-origin hosted UI. Header-token
    # clients remain compatible; the public health endpoint remains available.
    browser_authenticated = False
    if browser_auth_enabled and path != "/api/health":
        browser_authenticated = valid_browser_credentials(request.headers.get("Authorization", ""))
        api_authenticated = (
            path.startswith("/api/")
            and bool(config.api_token)
            and secrets.compare_digest(
                request.headers.get("X-HocVu-Token", "").encode("utf-8"),
                config.api_token.encode("utf-8"),
            )
        )
        if not browser_authenticated and not api_authenticated:
            return JSONResponse(
                status_code=401,
                content={"error": "Sign in with username hocvu and your access password."},
                headers={"WWW-Authenticate": 'Basic realm="HocVu AI", charset="UTF-8"'},
            )

    if path.startswith("/api/") and request.method not in {"GET", "HEAD", "OPTIONS"}:
        # HTTP Basic credentials are ambient browser authority, so authentication
        # alone cannot protect uploads/deletes from cross-site form submissions.
        # Replit terminates HTTPS at its proxy and forwards the original scheme.
        scheme = request.headers.get("X-Forwarded-Proto", request.url.scheme).split(",")[0].strip()
        expected_origin = f"{scheme}://{request.url.netloc}"
        allowed_origins = trusted_origins | {expected_origin.lower()}
        origin = request.headers.get("Origin")
        if (
            request.headers.get("Sec-Fetch-Site") == "cross-site"
            or (origin is not None and origin.lower() not in allowed_origins)
            or (browser_authenticated and origin is None)
        ):
            return JSONResponse(status_code=403, content={"error": "Cross-site changes are not allowed."})

    # Kiểm tra bảo vệ API nếu mở ra mạng công cộng
    if path.startswith("/api/") and path != "/api/health":
        if requires_api_token and not browser_authenticated:
            token = request.headers.get("X-HocVu-Token", "")
            if not config.api_token or not secrets.compare_digest(token.encode("utf-8"), config.api_token.encode("utf-8")):
                return JSONResponse(status_code=401, content={"error": "API token is required for network access."})

    response = await call_next(request)
    return response


# ── Các Endpoint Nghiệp vụ (API Routes) ──────────────────────────────────────
@app.get("/api/health", summary="Kiểm tra trạng thái hệ thống")
def health_check():
    eng = get_engine()
    return {
        "status": "ok",
        "documents": len(eng.list_documents()),
        "voice": "edge-tts+browser",
        "retrieval": eng.searcher.provider,
        "semantic_error": eng.searcher.semantic_error,
        "api_framework": "FastAPI/Uvicorn",
        "api_version": "answer-cards-1",
    }


@app.post("/api/ask", summary="Đặt câu hỏi tư vấn quy chế")
async def ask_question(payload: AskRequest):
    session_id = payload.session_id or str(uuid.uuid4())
    response = await run_in_threadpool(
        _call_engine, "ask",
        question=payload.question,
        session_id=session_id,
        ref_date=payload.ref_date,
        with_audio=bool(payload.with_audio),
        use_ai=bool(payload.use_ai),
    )
    result = response.to_dict()

    # Nếu client yêu cầu kèm âm thanh server
    if payload.with_audio and not result.get("audio_url"):
        try:
            vm = await run_in_threadpool(get_voice_manager)
            audio_url, _ = await vm.generate_audio_file(response.answer, prefix="ask")
            result["audio_url"] = audio_url
        except Exception:
            pass
        # Audio generation awaits network I/O after ask has saved its answer.
        # Do not return that answer if DELETE completed in the meantime.
        await run_in_threadpool(_call_engine, "ensure_session_open", session_id)

    return result


@app.get("/api/documents", summary="Danh sách tài liệu đã lập chỉ mục")
def list_documents():
    eng = get_engine()
    return eng.list_documents()


@app.post("/api/documents/upload", status_code=status.HTTP_201_CREATED, summary="Tải lên tài liệu quy chế mới")
async def upload_document(
    file: UploadFile = File(...),
    ocr: Optional[str] = Form(""),
    order: Optional[str] = Form(""),
    decision_number: Optional[str] = Form(""),
    article_clause: Optional[str] = Form(""),
    document_date: Optional[str] = Form(""),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="Hãy chọn một tệp PDF, DOCX hoặc ảnh.")
    
    use_ocr = str(ocr).strip().lower() in {"1", "true", "on", "yes"}
    metadata = {
        "order": order or "",
        "decision_number": decision_number or "",
        "article_clause": article_clause or "",
        "document_date": document_date or "",
    }
    async with _document_write_lock:
        content = await file.read(DocumentRepository.max_bytes + 1)
        if len(content) > DocumentRepository.max_bytes:
            raise HTTPException(status_code=400, detail="Kích thước tệp vượt quá 25 MB.")
        try:
            return await run_in_threadpool(
                _call_engine, "add_document", file.filename, content,
                use_ocr=use_ocr, metadata=metadata,
            )
        except DocumentError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Không thể đọc tệp: {exc}")


@app.get("/api/documents/{item_id}/text", summary="Xem nội dung văn bản trích xuất")
def document_text(item_id: str):
    eng = get_engine()
    try:
        return eng.document_text(item_id)
    except DocumentError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.delete("/api/documents/{item_id}", summary="Xóa tài liệu khỏi kho dữ liệu")
async def remove_document(item_id: str):
    try:
        await _mutate_documents("remove_document", item_id)
        return {"status": "deleted"}
    except DocumentError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.patch("/api/documents/{item_id}/date", summary="Sửa ngày áp dụng và cập nhật chỉ mục")
async def update_document_date(item_id: str, payload: DocumentDateRequest):
    try:
        return await _mutate_documents("update_document_date", item_id, payload.document_date)
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except DocumentError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Chưa thể cập nhật ngày và chỉ mục. Hãy thử lại; ngày áp dụng cũ được giữ nguyên.",
        ) from exc



@app.post("/api/documents/reindex", summary="Tái lập toàn bộ chỉ mục tìm kiếm")
async def reindex_documents():
    return await _mutate_documents("rebuild_index")


@app.get("/api/history", summary="Lấy lịch sử hội thoại theo phiên")
def get_history(response: Response, session_id: str = Query("", description="Mã phiên hội thoại")):
    response.headers["Cache-Control"] = "no-store"
    eng = get_engine()
    return eng.history(session_id)


@app.get("/api/history/status", summary="Kiểm tra hội thoại đã bị xóa hay chưa")
def history_status(
    response: Response,
    session_id: str = Query(..., min_length=1, description="Mã chính xác của phiên"),
):
    response.headers["Cache-Control"] = "no-store"
    return _call_engine("history_status", session_id)


@app.get("/api/suggestions", summary="Lấy danh mục câu hỏi gợi ý")
def get_suggestions():
    eng = get_engine()
    return eng.suggestion_topics()


@app.delete("/api/history", summary="Xóa vĩnh viễn lịch sử của đúng một phiên")
async def delete_history(
    request: Request,
    session_id: str = Query(
        ..., min_length=1,
        description="Mã chính xác của phiên cần xóa",
    ),
):
    if len(request.query_params.getlist("session_id")) != 1:
        raise HTTPException(status_code=422, detail="Chỉ được chọn một mã phiên để xóa.")
    try:
        validate_session_id(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    deleted = await run_in_threadpool(_call_engine, "delete_history", session_id)
    return {"status": "deleted", "session_id": session_id, "deleted_turns": deleted}


# ── Endpoint Xử lý Giọng nói (Server-side Edge-TTS) ──────────────────────────
@app.get("/api/tts", summary="Tổng hợp giọng nói tiếng Việt (GET stream)")
async def tts_get(
    text: str = Query(..., description="Văn bản cần đọc"),
    voice: Optional[str] = Query(DEFAULT_VOICE, description="Giọng đọc"),
    rate: Optional[str] = Query(DEFAULT_RATE, pattern=RATE_PATTERN, max_length=12, description="Tốc độ đọc"),
):
    vm = await run_in_threadpool(get_voice_manager)
    cleaned = clean_text_for_tts(text)
    if not cleaned:
        raise HTTPException(status_code=400, detail="Văn bản rỗng.")
    try:
        audio_bytes = await vm.synthesize(cleaned, voice=voice or DEFAULT_VOICE, rate=rate or DEFAULT_RATE)
        return StreamingResponse(
            io.BytesIO(audio_bytes),
            media_type="audio/mpeg",
            headers={"Content-Disposition": "inline; filename=speech.mp3"},
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Lỗi tổng hợp giọng nói: {exc}")


@app.post("/api/tts", summary="Tổng hợp giọng nói tiếng Việt (POST)")
async def tts_post(payload: TTSRequest):
    vm = await run_in_threadpool(get_voice_manager)
    cleaned = clean_text_for_tts(payload.text)
    if not cleaned:
        raise HTTPException(status_code=400, detail="Văn bản rỗng.")
    try:
        audio_url, _ = await vm.generate_audio_file(
            cleaned, voice=payload.voice or DEFAULT_VOICE, rate=payload.rate or DEFAULT_RATE,
        )
        return {"status": "ok", "audio_url": audio_url}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Lỗi tổng hợp giọng nói: {exc}")


@app.get("/api/audio/{filename}", summary="Phát file âm thanh đã lưu")
async def get_audio_file(filename: str):
    audio_root = AUD.resolve()
    try:
        file_path = (audio_root / filename).resolve()
    except (ValueError, OSError, RuntimeError):
        raise HTTPException(status_code=404, detail="Audio not found")
    if (
        not file_path.is_relative_to(audio_root)
        or Path(filename).name != filename
        or "\\" in filename
        or file_path.suffix.lower() != ".mp3"
    ):
        raise HTTPException(status_code=404, detail="Audio not found")
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Audio not found")
    return FileResponse(file_path, media_type="audio/mpeg")


# ── Phục vụ Giao diện Người dùng (Static Files) ──────────────────────────────
@app.get("/", include_in_schema=False)
async def serve_index():
    return FileResponse(UI / "index.html")


@app.get("/documents.html", include_in_schema=False)
async def serve_docs_page():
    return FileResponse(UI / "documents.html")


# Mount static assets (css, js, vendor)
app.mount("/", StaticFiles(directory=str(UI)), name="ui")


# ── Hàm Khởi chạy Máy chủ Uvicorn ────────────────────────────────────────────
def main(host: str = "127.0.0.1", port: int = 8000, verbose: bool = False, open_browser: bool = False):
    global engine
    if requires_api_token and not config.api_token:
        raise RuntimeError("Hãy đặt HV_API_TOKEN để bảo vệ tài liệu và API trước khi chạy server.")

    ensure_dirs()
    engine = get_engine()
    get_voice_manager()

    SERVER_META.write_text(json.dumps({"pid": os.getpid(), "port": port, "server": "FastAPI/Uvicorn"}), encoding="utf-8")
    url = f"http://{host}:{port}"
    print(f"HocVu AI (FastAPI + Edge-TTS) is running at {url}")
    if app.docs_url:
        print(f"Interactive API Docs available at {url}/docs")

    if open_browser:
        webbrowser.open(url)

    try:
        log_lvl = "debug" if verbose else "info"
        # Keep the transport peer intact for our explicit trusted-proxy policy.
        uvicorn.run(app, host=host, port=port, log_level=log_lvl, proxy_headers=False)
    finally:
        SERVER_META.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
