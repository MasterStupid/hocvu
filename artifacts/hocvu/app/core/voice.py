"""Asynchronous Edge-TTS synthesis and audio-file caching."""
from __future__ import annotations

import asyncio
import hashlib
import re
from pathlib import Path
import time
from typing import AsyncIterator
from .settings import AUD
from .index_storage import atomic_write


DEFAULT_VOICE = "vi-VN-HoaiMyNeural"  # Nữ miền Bắc
MALE_VOICE = "vi-VN-NamMinhNeural"    # Nam miền Bắc
DEFAULT_RATE = "+0%"
RATE_PATTERN = r"^[+-][0-9]+%$"
DEFAULT_CACHE_MAX_FILES = 200
DEFAULT_CACHE_MAX_BYTES = 50 * 1024 * 1024
DEFAULT_CACHE_TTL_SECONDS = 86400


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
    # Rút gọn các trích dẫn dạng [Nguồn: ...] hoặc [1]
    cleaned = re.sub(r'\[(?:Nguồn|Tham khảo):[^\]]+\]', '', cleaned)
    cleaned = re.sub(r'\[\d+\]', '', cleaned)
    # Chuẩn hóa khoảng trắng
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned


class VoiceManager:
    """Tổng hợp giọng nói Edge-TTS; nhận dạng do trình duyệt thực hiện."""

    def __init__(self, audio_dir: Path | None = None):
        self.audio_dir = audio_dir or AUD
        self.audio_dir.mkdir(parents=True, exist_ok=True)

    async def stream_synthesize(
        self,
        text: str,
        voice: str = DEFAULT_VOICE,
        rate: str = DEFAULT_RATE,
        pitch: str = "+0Hz",
    ) -> AsyncIterator[bytes]:
        """Phát luồng âm thanh MP3 từng phần trực tiếp từ Edge-TTS để giảm độ trễ."""
        cleaned = clean_text_for_tts(text)
        rate = normalize_rate(rate)
        if not cleaned:
            return
        import edge_tts

        communicator = edge_tts.Communicate(
            text=cleaned,
            voice=voice,
            rate=rate,
            pitch=pitch,
        )
        async for chunk in communicator.stream():
            if chunk.get("type") == "audio" and chunk.get("data"):
                yield chunk["data"]

    async def synthesize(
        self,
        text: str,
        voice: str = DEFAULT_VOICE,
        rate: str = DEFAULT_RATE,
        pitch: str = "+0Hz",
    ) -> bytes:
        """Tổng hợp giọng nói tiếng Việt chất lượng cao bằng Microsoft Edge TTS."""
        chunks = [
            chunk async for chunk in self.stream_synthesize(
                text, voice=voice, rate=rate, pitch=pitch,
            )
        ]
        return b"".join(chunks)

    def prune_cache(
        self,
        *,
        max_files: int = DEFAULT_CACHE_MAX_FILES,
        max_bytes: int = DEFAULT_CACHE_MAX_BYTES,
        ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
        keep: Path | None = None,
    ) -> int:
        """Dọn các tệp cache MP3 hết hạn hoặc vượt giới hạn dung lượng (LRU theo mtime)."""
        now = time.time()
        removed = 0
        entries: list[tuple[float, int, Path]] = []
        keep_resolved = keep.resolve() if keep is not None else None
        try:
            candidates = list(self.audio_dir.iterdir())
        except OSError:
            return 0
        for path in candidates:
            if path.is_symlink() or path.suffix.lower() != ".mp3":
                continue
            try:
                if not path.is_file():
                    continue
                if keep_resolved is not None and path.resolve() == keep_resolved:
                    continue
                stat = path.stat()
            except OSError:
                continue
            if ttl_seconds > 0 and (now - stat.st_mtime) > ttl_seconds:
                try:
                    path.unlink()
                    removed += 1
                except OSError:
                    pass
                continue
            entries.append((stat.st_mtime, stat.st_size, path))

        entries.sort(key=lambda item: item[0])  # oldest first
        total_files = len(entries) + (1 if keep_resolved is not None and _cached_audio(keep) else 0)
        keep_size = keep.stat().st_size if (keep is not None and _cached_audio(keep)) else 0
        total_bytes = sum(size for _, size, _ in entries) + keep_size
        for _, size, path in entries:
            if total_files <= max_files and total_bytes <= max_bytes:
                break
            try:
                path.unlink()
                removed += 1
                total_files -= 1
                total_bytes -= size
            except OSError:
                pass
        return removed

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
            await asyncio.to_thread(self.prune_cache, keep=filepath)

        return f"/api/audio/{filename}", filepath
