"""Optional cloud Speech-to-Text fallback for browsers without Web Speech API.

Reuses operator-configured Gemini or OpenAI credentials without introducing
heavy local speech dependencies. Audio payloads are strictly size- and
type-bounded before forwarding.
"""
from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
import uuid
from urllib.parse import quote, urlsplit, urlunsplit

from .nlp import normalize_stt_terms
from .settings import clean_api_key


MAX_AUDIO_BYTES = 2 * 1024 * 1024  # 2 MB (~30s compressed speech)

ALLOWED_AUDIO_TYPES: dict[str, str] = {
    "audio/webm": ".webm",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/m4a": ".m4a",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/ogg": ".ogg",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/aac": ".aac",
}


class STTError(RuntimeError):
    pass


def normalize_audio_mime(content_type: str | None) -> str:
    raw = (content_type or "").split(";", 1)[0].strip().lower()
    if raw not in ALLOWED_AUDIO_TYPES:
        raise STTError("Định dạng âm thanh không được hỗ trợ. Hãy gửi WebM, MP4/M4A, MP3, OGG hoặc WAV.")
    return raw


class CloudSTT:
    """Transcribe short Vietnamese voice questions via configured Gemini or OpenAI API."""

    def __init__(self, config):
        self.config = config

    @property
    def provider(self) -> str:
        gemini_key = clean_api_key(getattr(self.config, "gemini_key", ""))
        openai_key = clean_api_key(getattr(self.config, "openai_key", ""))
        preferred = getattr(self.config, "llm_backend", "local")
        if preferred == "openai" and openai_key:
            return "openai"
        if preferred == "gemini" and gemini_key:
            return "gemini"
        if gemini_key:
            return "gemini"
        if openai_key:
            return "openai"
        return ""

    @property
    def available(self) -> bool:
        return bool(self.provider)

    def transcribe(self, audio_bytes: bytes, content_type: str) -> str:
        if not self.available:
            raise STTError("Dịch vụ nhận dạng giọng nói dự phòng chưa được cấu hình trên máy chủ.")
        if not audio_bytes:
            raise STTError("Tệp âm thanh rỗng.")
        if len(audio_bytes) > MAX_AUDIO_BYTES:
            raise STTError("Đoạn ghi âm quá dài (tối đa 2 MB).")
        mime = normalize_audio_mime(content_type)
        if self.provider == "gemini":
            text = self._transcribe_gemini(audio_bytes, mime)
        else:
            text = self._transcribe_openai(audio_bytes, mime)
        cleaned = normalize_stt_terms(text.strip())
        if not cleaned:
            raise STTError("Không nhận dạng được lời nói trong đoạn ghi âm.")
        return cleaned[:4000]

    def _transcribe_gemini(self, audio_bytes: bytes, mime: str) -> str:
        prompt = (
            "Chép chính xác lời nói tiếng Việt trong đoạn ghi âm thành một câu hỏi văn bản. "
            "Giữ đúng các thuật ngữ học vụ như IELTS, TOEIC, GPA, ĐRL, HBKKHT, tín chỉ, bảo lưu, học phần. "
            "Chỉ trả về đúng câu đã nghe, không thêm giải thích hay dấu ngoặc kép."
        )
        payload = {
            "contents": [{
                "role": "user",
                "parts": [
                    {"text": prompt},
                    {"inlineData": {"mimeType": mime, "data": base64.b64encode(audio_bytes).decode("ascii")}},
                ],
            }],
            "generationConfig": {"maxOutputTokens": 512, "temperature": 0.0},
        }
        parts = urlsplit(self.config.gemini_url)
        path = parts.path.rstrip("/")
        if not path.endswith(":generateContent"):
            path = f"{path}/models/{quote(self.config.gemini_model, safe='-._')}:generateContent"
        endpoint = urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))
        req = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "x-goog-api-key": clean_api_key(self.config.gemini_key),
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=25) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise STTError("Không thể kết nối dịch vụ nhận dạng giọng nói lúc này.") from exc
        texts: list[str] = []
        for candidate in body.get("candidates", []):
            for part in candidate.get("content", {}).get("parts", []):
                if isinstance(part.get("text"), str):
                    texts.append(part["text"])
            if texts:
                break
        return " ".join(texts).strip()

    def _transcribe_openai(self, audio_bytes: bytes, mime: str) -> str:
        boundary = f"----hocvu-{uuid.uuid4().hex}"
        ext = ALLOWED_AUDIO_TYPES[mime]
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="model"\r\n\r\n'
            f"whisper-1\r\n"
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="language"\r\n\r\n'
            f"vi\r\n"
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="voice{ext}"\r\n'
            f"Content-Type: {mime}\r\n\r\n"
        ).encode("utf-8") + audio_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")
        parts = urlsplit(self.config.openai_url)
        path = parts.path.rstrip("/")
        if not path.endswith("/audio/transcriptions"):
            path = f"{path}/audio/transcriptions"
        endpoint = urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))
        req = urllib.request.Request(
            endpoint,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {clean_api_key(self.config.openai_key)}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=25) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise STTError("Không thể kết nối dịch vụ nhận dạng giọng nói lúc này.") from exc
        return str(data.get("text") or "").strip()
