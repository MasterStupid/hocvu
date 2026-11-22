"""Asynchronous Edge-TTS synthesis and audio-file caching."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from pathlib import Path
from .settings import AUD
from .index_storage import atomic_write


DEFAULT_VOICE = "vi-VN-HoaiMyNeural"  # Nữ miền Bắc
MALE_VOICE = "vi-VN-NamMinhNeural"    # Nam miền Bắc
DEFAULT_RATE = "+0%"
RATE_PATTERN = r"^[+-][0-9]+%$"
# The free Edge read-aloud endpoint intermittently closes a request without
# audio, then serves the same text on the next attempt. Retry briefly before
# reporting the provider as unavailable.
SYNTHESIS_ATTEMPTS = 3
SYNTHESIS_RETRY_DELAY = 0.4

logger = logging.getLogger(__name__)


class SpeechUnavailable(Exception):
    """The external speech provider returned no audio after bounded retries."""


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
    """Tổng hợp giọng nói Edge-TTS; nhận dạng do trình duyệt thực hiện."""

    def __init__(self, audio_dir: Path | None = None):
        self.audio_dir = audio_dir or AUD
        self.audio_dir.mkdir(parents=True, exist_ok=True)

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

        last_error: Exception | None = None
        for attempt in range(1, SYNTHESIS_ATTEMPTS + 1):
            try:
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
                audio = b"".join(chunks)
                if audio:
                    return audio
                last_error = SpeechUnavailable("empty audio stream")
            except (ValueError, TypeError):
                # Invalid parameters cannot succeed on a retry.
                raise
            except Exception as exc:  # provider/network failures are transient
                last_error = exc
            logger.warning(
                "Edge TTS attempt %d/%d returned no audio (%s, voice=%s, chars=%d)",
                attempt, SYNTHESIS_ATTEMPTS, type(last_error).__name__, voice, len(cleaned),
            )
            if attempt < SYNTHESIS_ATTEMPTS:
                await asyncio.sleep(SYNTHESIS_RETRY_DELAY * attempt)
        raise SpeechUnavailable(
            "Dịch vụ giọng đọc tạm thời không phản hồi."
        ) from last_error

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
