import asyncio
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import threading
import unittest
from unittest.mock import AsyncMock, Mock, patch

import httpx

from core.index_storage import atomic_write
from core.voice import DEFAULT_RATE, DEFAULT_VOICE, MALE_VOICE, VoiceManager, normalize_rate
from server import app as server


class VoiceRateTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.manager = VoiceManager(audio_dir=Path(directory.name))
        self.manager.synthesize = AsyncMock(side_effect=lambda text, voice, rate: f"audio:{voice}:{rate}".encode())

    async def test_requested_rate_reaches_synthesis(self):
        _, path = await self.manager.generate_audio_file("**Xin chào**", voice=MALE_VOICE, rate="+10%")
        self.manager.synthesize.assert_awaited_once_with("Xin chào", voice=MALE_VOICE, rate="+10%")
        self.assertEqual(path.read_bytes(), f"audio:{MALE_VOICE}:+10%".encode())

    async def test_different_rates_and_voices_have_distinct_cache_files(self):
        paths = []
        for voice, rate in (
            (DEFAULT_VOICE, "+0%"), (DEFAULT_VOICE, "+10%"),
            (DEFAULT_VOICE, "-10%"), (MALE_VOICE, "+10%"),
        ):
            url, path = await self.manager.generate_audio_file("Xin chào", voice=voice, rate=rate)
            self.assertTrue(url.endswith(path.name))
            self.assertEqual(path.read_bytes(), f"audio:{voice}:{rate}".encode())
            paths.append(path)
        self.assertEqual(len(set(paths)), 4)
        self.assertEqual(self.manager.synthesize.await_count, 4)

    async def test_same_normalized_rate_and_text_reuse_cache(self):
        first = await self.manager.generate_audio_file("**Xin chào**", rate="+010%")
        second = await self.manager.generate_audio_file("Xin chào", rate="+10%")
        self.assertEqual(first, second)
        self.manager.synthesize.assert_awaited_once_with("Xin chào", voice=DEFAULT_VOICE, rate="+10%")

    async def test_omitted_and_null_rate_use_default(self):
        first = await self.manager.generate_audio_file("Xin chào")
        second = await self.manager.generate_audio_file("Xin chào", rate=None)
        self.assertEqual(first, second)
        self.manager.synthesize.assert_awaited_once_with("Xin chào", voice=DEFAULT_VOICE, rate=DEFAULT_RATE)

    async def test_invalid_rates_fail_before_synthesis_or_cache_write(self):
        for rate in ("fast", "10%", "+10", "", "+10%\n", "+12345678901%", 10):
            with self.subTest(rate=rate):
                with self.assertRaises(ValueError):
                    await self.manager.generate_audio_file("Xin chào", rate=rate)
        self.manager.synthesize.assert_not_awaited()
        self.assertEqual(list(self.manager.audio_dir.iterdir()), [])

    async def test_empty_cache_is_recreated(self):
        _, path = await self.manager.generate_audio_file("Xin chào", rate="+10%")
        path.write_bytes(b"")
        await self.manager.generate_audio_file("Xin chào", rate="+10%")
        self.assertEqual(self.manager.synthesize.await_count, 2)
        self.assertTrue(path.stat().st_size)

    async def test_cache_write_is_atomic_and_off_the_event_loop(self):
        loop_thread = threading.get_ident()
        def write(path, content):
            self.assertNotEqual(threading.get_ident(), loop_thread)
            self.assertFalse(path.exists())
            atomic_write(path, content)
        with patch("core.voice.atomic_write", side_effect=write) as commit:
            _, path = await self.manager.generate_audio_file("Xin chào", rate="+10%")
        commit.assert_called_once()
        self.assertTrue(path.exists())

    async def test_synthesize_passes_canonical_rate_to_edge_communicator(self):
        async def stream():
            yield {"type": "WordBoundary"}
            yield {"type": "audio", "data": b"first"}
            yield {"type": "audio", "data": b"second"}
        communicator = Mock(return_value=SimpleNamespace(stream=stream))
        manager = VoiceManager(audio_dir=self.manager.audio_dir)
        with patch.dict(sys.modules, {"edge_tts": SimpleNamespace(Communicate=communicator)}):
            audio = await manager.synthesize("**Xin chào**", voice=MALE_VOICE, rate="+010%")
        self.assertEqual(audio, b"firstsecond")
        communicator.assert_called_once_with(
            text="Xin chào", voice=MALE_VOICE, rate="+10%", pitch="+0Hz",
        )

    def test_rate_normalization(self):
        for raw, expected in ((None, "+0%"), ("-0%", "+0%"), ("+000%", "+0%"), ("-010%", "-10%")):
            self.assertEqual(normalize_rate(raw), expected)


class TtsRateApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.audio = Path(directory.name)
        self.manager = VoiceManager(audio_dir=self.audio)
        self.manager.synthesize = AsyncMock(side_effect=lambda text, voice, rate: f"audio:{rate}".encode())
        for item in (
            patch.object(server, "requires_api_token", False),
            patch.object(server, "browser_auth_enabled", False),
            patch.object(server, "request_limiter", server.SlidingWindowLimiter()),
            patch.object(server, "get_voice_manager", return_value=self.manager),
            patch.object(server, "AUD", self.audio),
        ):
            item.start()
            self.addCleanup(item.stop)
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app), base_url="http://test",
            headers={"Origin": "http://test"},
        )
        self.addAsyncCleanup(self.client.aclose)

    async def test_post_rates_are_forwarded_cached_separately_and_served(self):
        urls = []
        for rate in ("+10%", "-10%", "+0%"):
            response = await self.client.post("/api/tts", json={"text": "Xin chào", "rate": rate})
            self.assertEqual(response.status_code, 200, response.text)
            url = response.json()["audio_url"]
            audio = await self.client.get(url)
            self.assertEqual(audio.content, f"audio:{rate}".encode())
            urls.append(url)
        self.assertEqual(len(set(urls)), 3)
        again = await self.client.post("/api/tts", json={"text": "Xin chào", "rate": "+10%"})
        self.assertEqual(again.json()["audio_url"], urls[0])
        self.assertEqual(self.manager.synthesize.await_count, 3)

    async def test_post_default_and_explicit_null_keep_default_rate(self):
        omitted = await self.client.post("/api/tts", json={"text": "Xin chào"})
        explicit_null = await self.client.post("/api/tts", json={"text": "Xin chào", "rate": None})
        self.assertEqual(omitted.status_code, 200)
        self.assertEqual(omitted.json(), explicit_null.json())
        self.manager.synthesize.assert_awaited_once_with("Xin chào", voice=DEFAULT_VOICE, rate="+0%")

    async def test_post_preserves_voice_and_requested_rate(self):
        response = await self.client.post(
            "/api/tts", json={"text": "Xin chào", "voice": MALE_VOICE, "rate": "+20%"},
        )
        self.assertEqual(response.status_code, 200)
        self.manager.synthesize.assert_awaited_once_with("Xin chào", voice=MALE_VOICE, rate="+20%")

    async def test_get_supports_the_same_rate_contract(self):
        response = await self.client.get("/api/tts", params={"text": "Xin chào", "rate": "-10%"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"audio:-10%")
        self.manager.synthesize.assert_awaited_once_with("Xin chào", voice=DEFAULT_VOICE, rate="-10%")

    async def test_malformed_rates_are_rejected_without_calling_synthesis(self):
        for rate in ("fast", "10%", "+10", "", "+12345678901%"):
            post = await self.client.post("/api/tts", json={"text": "Xin chào", "rate": rate})
            get = await self.client.get("/api/tts", params={"text": "Xin chào", "rate": rate})
            self.assertEqual(post.status_code, 422, post.text)
            self.assertEqual(get.status_code, 422, get.text)
        self.manager.synthesize.assert_not_awaited()
