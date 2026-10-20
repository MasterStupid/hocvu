"""Voice capability module with Edge-TTS server synthesis and browser contract."""
from __future__ import annotations

import asyncio
import hashlib
import re
from pathlib import Path
from typing import Optional

from .models import SpeechResult
from .settings import AUD
from .index_storage import atomic_write


DEFAULT_VOICE = "vi-VN-HoaiMyNeural"  # Nữ miền Bắc
MALE_VOICE = "vi-VN-NamMinhNeural"    # Nam miền Bắc
DEFAULT_RATE = "+0%"
RATE_PATTERN = r"^[+-][0-9]+%$"


def normalize_rate(rate: str | None = DEFAULT_RATE) -> str:
    value = DEFAULT_RATE if rate is None else rate
    if not isinstance(value, str) or len(value) > 12 or not re.fullmatch(RATE_PATTERN, value):
        raise ValueError("Tốc độ đọc phải có dạng +10%, -10% hoặc +0%.")
    return f"{int(value[:-1]):+d}%"


def _cached_audio(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0
    except FileNotFoundError:
        return False


def clean_text_for_tts(text: str) -> str:
    """Chuẩn hóa văn bản trước khi đọc bằng TTS."""
    if not text:
        return ""
    # Loại bỏ markdown symbols
    cleaned = re.sub(r'[*_#`~]', '', text)
    # Loại bỏ các đường link hoặc thẻ HTML
    cleaned = re.sub(r'<[^>]+>', '', cleaned)
    cleaned = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', cleaned)
    # Rút gọn các trích dẫn dạng [Nguồn: ...]
    cleaned = re.sub(r'\[(?:Nguồn|Tham khảo):[^\]]+\]', '', cleaned)
    # Chuẩn hóa khoảng trắng
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned


class VoiceManager:
    """Quản lý tổng hợp và nhận dạng giọng nói."""

    def __init__(self, config=None, audio_dir: Path | None = None):
        self.config = config
        self.audio_dir = audio_dir or AUD
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self.default_voice = DEFAULT_VOICE

    def speech_to_text(self, audio_path: str) -> SpeechResult:
        """Hợp đồng nhận dạng giọng nói (Browser-First với Web Speech API)."""
        return SpeechResult(
            text="",
            confidence=0.0,
            lang="vi",
            provider="browser",
            note="Nhận dạng giọng nói được thực hiện trực tiếp trên trình duyệt qua Web Speech API.",
        )

    async def synthesize(
        self,
        text: str,
        voice: str = DEFAULT_VOICE,
        rate: str = DEFAULT_RATE,
        pitch: str = "+0Hz",
    ) -> bytes:
        """Tổng hợp giọng nói tiếng Việt chất lượng cao bằng Microsoft Edge TTS."""
        cleaned = clean_text_for_tts(text)
        rate = normalize_rate(rate)
        if not cleaned:
            return b""
        import edge_tts

        communicator = edge_tts.Communicate(
            text=cleaned,
            voice=voice,
            rate=rate,
            pitch=pitch,
        )
        chunks = []
        async for chunk in communicator.stream():
            if chunk["type"] == "audio":
                chunks.append(chunk["data"])
        return b"".join(chunks)

    async def generate_audio_file(
        self,
        text: str,
        voice: str = DEFAULT_VOICE,
        prefix: str = "reply",
        rate: str = DEFAULT_RATE,
    ) -> tuple[str, Path]:
        """Tổng hợp và lưu file MP3 vào thư mục audio, trả về (url_path, file_path)."""
        cleaned = clean_text_for_tts(text)
        rate = normalize_rate(rate)
        # Băm nội dung để tái sử dụng cache âm thanh nếu câu trả lời trùng nhau
        hash_id = hashlib.md5(f"{voice}:{rate}:{cleaned}".encode("utf-8")).hexdigest()[:12]
        filename = f"{prefix}_{hash_id}.mp3"
        filepath = self.audio_dir / filename

        if not await asyncio.to_thread(_cached_audio, filepath):
            audio_bytes = await self.synthesize(cleaned, voice=voice, rate=rate)
            await asyncio.to_thread(atomic_write, filepath, audio_bytes)

        return f"/api/audio/{filename}", filepath

    def text_to_speech(self, text: str) -> Optional[bytes]:
        """Wrapper đồng bộ cho tổng hợp giọng nói."""
        try:
            return asyncio.run(self.synthesize(text))
        except Exception:
            return None
