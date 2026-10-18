"""FastAPI RESTful web service for HocVu AI with Swagger UI and Edge-TTS support."""
from __future__ import annotations

import io
import base64
import binascii
import json
import os
import re
import secrets
import time
import uuid
import webbrowser
from pathlib import Path
from typing import Any, Dict, List, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response, UploadFile, File, Form, Query, status
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from core.engine import HocVuEngine, build_index
from core.documents import DocumentError, DocumentRepository
from core.settings import AUD, INDEX_JSON, SERVER_META, UI, ensure_dirs, load_config
from core.voice import VoiceManager, clean_text_for_tts, DEFAULT_VOICE, MALE_VOICE


# ── Global Engine & Voice State ──────────────────────────────────────────────
engine: HocVuEngine | None = None
voice_manager: VoiceManager | None = None
requires_api_token = False
config = load_config()
browser_auth_enabled = os.environ.get("HV_BROWSER_AUTH", "0") == "1"


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
        ensure_dirs()
        if not INDEX_JSON.exists():
            _, searcher = build_index(config, return_searcher=True)
            engine = HocVuEngine(config, searcher)
        else:
            engine = HocVuEngine.load(config, INDEX_JSON)
    return engine


def get_voice_manager() -> VoiceManager:
    global voice_manager
    if voice_manager is None:
        voice_manager = VoiceManager(config=config, audio_dir=AUD)
    return voice_manager


# ── Pydantic Request / Response Models ───────────────────────────────────────
class AskRequest(BaseModel):
    question: str = Field(..., description="Câu hỏi quy chế của sinh viên")
    session_id: Optional[str] = Field(None, description="Mã định danh phiên hội thoại")
    ref_date: Optional[str] = Field(None, description="Ngày tra cứu hiệu lực văn bản (YYYY-MM-DD)")
    with_audio: Optional[bool] = Field(False, description="Yêu cầu sinh kèm URL âm thanh phản hồi")
    use_ai: Optional[bool] = Field(False, description="Bật Google Gemini diễn đạt lại câu trả lời")


class TTSRequest(BaseModel):
    text: str = Field(..., description="Văn bản cần đọc")
    voice: Optional[str] = Field(DEFAULT_VOICE, description="Tên giọng đọc (vi-VN-HoaiMyNeural hoặc vi-VN-NamMinhNeural)")
    rate: Optional[str] = Field("+0%", description="Tốc độ đọc, ví dụ: +0%, +10%, -10%")


# ── Khởi tạo Ứng dụng FastAPI ────────────────────────────────────────────────
app = FastAPI(
    title="HocVu AI API",
    description="Hệ thống Trợ lý ảo tư vấn Quy chế Đào tạo Sinh viên (RAG & Voice Assistant) - ĐH Hải Phòng",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# The bundled UI and Netlify's API proxy are same-origin. Do not enable
# credentialed cross-origin browser access to the editable regulation corpus.

_request_times: dict[str, list[float]] = {}


@app.middleware("http")
async def rate_limit_and_auth_middleware(request: Request, call_next):
    client_ip = request.client.host if request.client else "127.0.0.1"
    path = request.url.path

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
        origin = request.headers.get("Origin")
        if (
            request.headers.get("Sec-Fetch-Site") == "cross-site"
            or (origin is not None and origin != expected_origin)
            or (browser_authenticated and origin is None)
        ):
            return JSONResponse(status_code=403, content={"error": "Cross-site changes are not allowed."})

    # Kiểm tra bảo vệ API nếu mở ra mạng công cộng
    if path.startswith("/api/") and path != "/api/health":
        if requires_api_token and not browser_authenticated:
            token = request.headers.get("X-HocVu-Token", "")
            if not config.api_token or not secrets.compare_digest(token.encode("utf-8"), config.api_token.encode("utf-8")):
                return JSONResponse(status_code=401, content={"error": "API token is required for network access."})

        # Rate limiting
        now = time.monotonic()
        recent = [stamp for stamp in _request_times.get(client_ip, []) if now - stamp < 60]
        if len(recent) >= config.rate_limit_per_minute:
            _request_times[client_ip] = recent
            return JSONResponse(status_code=429, content={"error": "Too many requests; try again in a minute."})
        recent.append(now)
        _request_times[client_ip] = recent

    response = await call_next(request)
    return response


# ── Các Endpoint Nghiệp vụ (API Routes) ──────────────────────────────────────
@app.get("/api/health", summary="Kiểm tra trạng thái hệ thống")
async def health_check():
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
    eng = get_engine()
    session_id = payload.session_id or str(uuid.uuid4())
    response = eng.ask(
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
            vm = get_voice_manager()
            audio_url, _ = await vm.generate_audio_file(response.answer, prefix="ask")
            result["audio_url"] = audio_url
        except Exception:
            pass

    return result


@app.get("/api/documents", summary="Danh sách tài liệu đã lập chỉ mục")
async def list_documents():
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
    eng = get_engine()
    if not file.filename:
        raise HTTPException(status_code=400, detail="Hãy chọn một tệp PDF, DOCX hoặc ảnh.")
    
    content = await file.read()
    if len(content) > DocumentRepository.max_bytes:
        raise HTTPException(status_code=400, detail="Kích thước tệp vượt quá 25 MB.")

    use_ocr = str(ocr).strip().lower() in {"1", "true", "on", "yes"}
    metadata = {
        "order": order or "",
        "decision_number": decision_number or "",
        "article_clause": article_clause or "",
        "document_date": document_date or "",
    }
    try:
        item = eng.add_document(file.filename, content, use_ocr=use_ocr, metadata=metadata)
        return item
    except DocumentError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Không thể đọc tệp: {exc}")


@app.get("/api/documents/{item_id}/text", summary="Xem nội dung văn bản trích xuất")
async def document_text(item_id: str):
    eng = get_engine()
    try:
        return eng.document_text(item_id)
    except DocumentError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.delete("/api/documents/{item_id}", summary="Xóa tài liệu khỏi kho dữ liệu")
async def remove_document(item_id: str):
    eng = get_engine()
    try:
        eng.remove_document(item_id)
        return {"status": "deleted"}
    except DocumentError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/api/documents/reindex", summary="Tái lập toàn bộ chỉ mục tìm kiếm")
async def reindex_documents():
    eng = get_engine()
    return eng.rebuild_index()


@app.get("/api/history", summary="Lấy lịch sử hội thoại theo phiên")
async def get_history(session_id: str = Query("", description="Mã phiên hội thoại")):
    eng = get_engine()
    return eng.history(session_id)


@app.get("/api/suggestions", summary="Lấy danh mục câu hỏi gợi ý")
async def get_suggestions():
    eng = get_engine()
    return eng.suggestion_topics()


# ── Endpoint Xử lý Giọng nói (Server-side Edge-TTS) ──────────────────────────
@app.get("/api/tts", summary="Tổng hợp giọng nói tiếng Việt (GET stream)")
async def tts_get(
    text: str = Query(..., description="Văn bản cần đọc"),
    voice: Optional[str] = Query(DEFAULT_VOICE, description="Giọng đọc"),
):
    vm = get_voice_manager()
    cleaned = clean_text_for_tts(text)
    if not cleaned:
        raise HTTPException(status_code=400, detail="Văn bản rỗng.")
    try:
        audio_bytes = await vm.synthesize(cleaned, voice=voice or DEFAULT_VOICE)
        return StreamingResponse(
            io.BytesIO(audio_bytes),
            media_type="audio/mpeg",
            headers={"Content-Disposition": "inline; filename=speech.mp3"},
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Lỗi tổng hợp giọng nói: {exc}")


@app.post("/api/tts", summary="Tổng hợp giọng nói tiếng Việt (POST)")
async def tts_post(payload: TTSRequest):
    vm = get_voice_manager()
    cleaned = clean_text_for_tts(payload.text)
    if not cleaned:
        raise HTTPException(status_code=400, detail="Văn bản rỗng.")
    try:
        audio_url, _ = await vm.generate_audio_file(cleaned, voice=payload.voice or DEFAULT_VOICE)
        return {"status": "ok", "audio_url": audio_url}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Lỗi tổng hợp giọng nói: {exc}")


@app.get("/api/audio/{filename}", summary="Phát file âm thanh đã lưu")
async def get_audio_file(filename: str):
    file_path = AUD / filename
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
    global requires_api_token, engine
    requires_api_token = host not in {"127.0.0.1", "localhost", "::1"}
    if requires_api_token and not config.api_token:
        raise RuntimeError("Khi mở server ra mạng, hãy đặt HV_API_TOKEN để bảo vệ tài liệu và API.")

    ensure_dirs()
    engine = get_engine()
    get_voice_manager()

    SERVER_META.write_text(json.dumps({"pid": os.getpid(), "port": port, "server": "FastAPI/Uvicorn"}), encoding="utf-8")
    url = f"http://{host}:{port}"
    print(f"HocVu AI (FastAPI + Edge-TTS) is running at {url}")
    print(f"Interactive API Docs available at {url}/docs")

    if open_browser:
        webbrowser.open(url)

    try:
        log_lvl = "debug" if verbose else "info"
        uvicorn.run(app, host=host, port=port, log_level=log_lvl)
    finally:
        SERVER_META.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
