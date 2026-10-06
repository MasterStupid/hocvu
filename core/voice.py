"""Voice capability contract for the browser-first pilot."""
from __future__ import annotations

from pathlib import Path

from .models import SpeechResult


class VoiceManager:
    def __init__(self, config, audio_dir: Path | None = None):
        self.config = config
        self.audio_dir = audio_dir

    def speech_to_text(self, audio_path: str) -> SpeechResult:
        return SpeechResult(
            text="", confidence=0.0, lang="vi", provider="browser",
            note="Nhận dạng giọng nói được thực hiện trực tiếp trên trình duyệt trong bản thử nghiệm.",
        )

    def text_to_speech(self, text: str) -> None:
        return None
