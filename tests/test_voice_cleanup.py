"""Keep browser recognition and active Edge-TTS independent of retired backends."""
from dataclasses import fields
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from core.engine import HocVuEngine
from core.models import Response
from core.nlp import tokenize
from core.searcher import HybridSearcher
from core.settings import AppConfig, load_config
from core.voice import VoiceManager
from server import app as server


class VoiceCleanupTests(unittest.TestCase):
    def test_retired_settings_are_not_loaded_or_advertised(self):
        with patch.dict(os.environ, {
            "HV_STT": "whisper", "HV_TTS": "local",
            "WHISPER_MODEL": "unused", "TTS_VOICE": "unused",
        }):
            config = load_config()
        names = {item.name for item in fields(config)}
        self.assertTrue(names.isdisjoint({"stt_backend", "tts_backend", "whisper_size", "tts_voice"}))
        self.assertTrue({"stt", "tts"}.isdisjoint(config.summary()))
        example = (Path(__file__).resolve().parents[1] / ".env.example").read_text()
        for setting in ("HV_STT", "HV_TTS", "WHISPER_MODEL", "TTS_VOICE"):
            self.assertNotIn(setting + "=", example)

    def test_retired_voice_entry_points_are_gone(self):
        self.assertFalse(hasattr(HocVuEngine, "ask_voice"))
        self.assertFalse(hasattr(VoiceManager, "speech_to_text"))
        self.assertFalse(hasattr(VoiceManager, "text_to_speech"))

    def test_text_engine_does_not_initialize_unused_audio_manager(self):
        config = AppConfig(semantic_enabled=False)
        searcher = HybridSearcher(config)
        searcher.build([])
        with patch("core.engine.session_store", return_value=Mock()):
            engine = HocVuEngine(config, searcher, documents=Mock(revision=None))
        self.assertFalse(hasattr(engine, "voice"))

    def test_server_still_initializes_edge_tts_lazily(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(server, "voice_manager", None), patch.object(server, "AUD", Path(directory)):
                manager = server.get_voice_manager()
                self.assertIsInstance(manager, VoiceManager)
                self.assertEqual(manager.audio_dir, Path(directory))
                self.assertIs(server.get_voice_manager(), manager)
                self.assertFalse(hasattr(manager, "config"))

    def test_legacy_chat_json_key_is_unchanged(self):
        response = Response(query="Xin chào", answer="Chào bạn").to_dict()
        self.assertIn("speech", response)
        self.assertIsNone(response["speech"])
        self.assertIn("audio_url", response)

    def test_tokenizer_and_dependencies_do_not_require_underthesea(self):
        self.assertEqual(tokenize("Điều kiện bảo lưu"), ["dieu", "kien", "bao", "luu"])
        import core.nlp as nlp
        self.assertFalse(hasattr(nlp, "word_tokenize_vi"))
        root = Path(__file__).resolve().parents[1]
        for name in ("requirements.txt", "requirements.production.txt"):
            self.assertNotIn("underthesea", (root / name).read_text().lower())
