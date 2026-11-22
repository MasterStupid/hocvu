"""Regression tests for voice streaming, STT fallback, RAG upgrades, LLM sync, and public catalog."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import httpx

from core.cards import build_card
from core.classifier import Classifier, Intent
from core.corpus import build_corpus
from core.engine import HocVuEngine
from core.llm import GroundedLLM
from core.models import Reference
from core.nlp import expand_academic_terms, normalize_stt_terms
from core.scenarios import is_underspecified_follow_up
from core.searcher import HybridSearcher
from core.semantic import SemanticEncoder
from core.settings import AppConfig
from core.splitter import split_regulation
from core.stt import CloudSTT, MAX_AUDIO_BYTES, STTError
from core.voice import DEFAULT_VOICE, VoiceManager
from server import app as server


class VoiceAndNlpUpgradeTests(unittest.IsolatedAsyncioTestCase):
    def test_thanks_and_farewell_are_distinct_from_greeting(self):
        classifier = Classifier()
        for phrase in ("Cảm ơn bạn nhé", "Cảm ơn nhiều!", "Thanks", "Tạm biệt bạn"):
            with self.subTest(phrase=phrase):
                self.assertEqual(classifier.classify(phrase), Intent.THANKS)
        self.assertEqual(classifier.classify("Xin chào bạn"), Intent.GREETING)

    def test_stt_normalization_and_colloquial_synonyms_are_idempotent(self):
        cases = [
            ("Sinh viên cần bao nhiêu tính chỉ đại cương?", "tín chỉ"),
            ("Điểm ai eo 5.5 được quy đổi ra sao?", "IELTS"),
            ("Điểm tô ích tối thiểu là bao nhiêu?", "TOEIC"),
            ("Em bị rớt môn đại cương thì sao?", "trượt học lại"),
            ("Khi nào sinh viên bị đuổi học?", "buộc thôi học"),
            ("Cần bao nhiêu tín chỉ để ra trường?", "tốt nghiệp"),
            ("Đóng tiền học muộn có bị phạt không?", "trễ hạn"),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                expanded = expand_academic_terms(raw)
                self.assertIn(expected.lower(), expanded.lower())
                self.assertEqual(expand_academic_terms(expanded), expanded)
        self.assertEqual(normalize_stt_terms("cảnh báo học bộ"), "cảnh báo học vụ")

    async def test_voice_manager_streams_and_prunes_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio_dir = Path(tmp)
            manager = VoiceManager(audio_dir=audio_dir)

            async def fake_stream():
                yield {"type": "WordBoundary"}
                yield {"type": "audio", "data": b"part1"}
                yield {"type": "audio", "data": b"part2"}

            communicator = Mock(return_value=types.SimpleNamespace(stream=fake_stream))
            with patch.dict(sys.modules, {"edge_tts": types.SimpleNamespace(Communicate=communicator)}):
                chunks = [c async for c in manager.stream_synthesize("Xin chào [1]", voice=DEFAULT_VOICE)]
            self.assertEqual(chunks, [b"part1", b"part2"])
            self.assertEqual(list(audio_dir.iterdir()), [])  # streaming does not write disk

            # Create 4 mp3 files with distinct ages + 1 non-mp3 file.
            keep_note = audio_dir / "keep.txt"
            keep_note.write_text("ignore", encoding="utf-8")
            old_expired = audio_dir / "expired.mp3"
            old_expired.write_bytes(b"0" * 10)
            os.utime(old_expired, (time.time() - 7200, time.time() - 7200))
            files = []
            for idx in range(3):
                p = audio_dir / f"f{idx}.mp3"
                p.write_bytes(b"x" * 20)
                os.utime(p, (time.time() - (30 - idx * 5), time.time() - (30 - idx * 5)))
                files.append(p)
            removed = manager.prune_cache(max_files=2, max_bytes=100, ttl_seconds=3600, keep=files[-1])
            self.assertEqual(removed, 2)  # expired.mp3 + oldest f0.mp3
            self.assertFalse(old_expired.exists())
            self.assertFalse(files[0].exists())
            self.assertTrue(files[1].exists())
            self.assertTrue(files[2].exists())
            self.assertTrue(keep_note.exists())


class RagAndLlmUpgradeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = AppConfig(semantic_enabled=False)
        cls.searcher = HybridSearcher(cls.config)
        cls.searcher.build([
            chunk for reg in build_corpus()
            for chunk in split_regulation(reg, 800, 1)
        ])

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.enterContext(patch("core.engine.SESSION_DB", self.root / "sessions.db"))
        self.enterContext(patch("core.engine.DOCS", self.root / "documents"))
        self.engine = HocVuEngine(self.config, self.searcher)

    def test_thanks_response_is_polite_not_greeting(self):
        resp = self.engine.ask("Cảm ơn bạn nhé", "s-thanks", record_session=False)
        self.assertFalse(resp.refused)
        self.assertEqual(resp.intent, "thanks")
        self.assertIn("Không có gì", resp.answer)
        self.assertNotIn("Chào bạn!", resp.answer)

    def test_colloquial_and_stt_queries_retrieve_grounded_answers(self):
        for query, expected_fragment in (
            ("Sinh viên cần bao nhiêu tính chỉ đại cương?", "45 tín chỉ"),
            ("Điểm ai eo 5.5 được quy đổi như thế nào?", "IELTS"),
            ("Bị cảnh báo học vụ bao nhiêu lần thì bị đuổi học?", "3 lần liên tiếp"),
        ):
            with self.subTest(query=query):
                resp = self.engine.ask(query, "s-colloq", ref_date="2026-10-20", record_session=False)
                self.assertFalse(resp.refused, resp.answer)
                self.assertIn(expected_fragment, resp.answer)

    def test_underspecified_multiturn_followup_inherits_root_without_contaminating_new_topics(self):
        self.assertTrue(is_underspecified_follow_up("Thế sinh viên năm nhất có được xét không?"))
        self.assertTrue(is_underspecified_follow_up("Mức tiền nhận được là bao nhiêu?"))
        self.assertFalse(is_underspecified_follow_up("Thế còn wifi?"))

        first = self.engine.ask("Điều kiện nhận học bổng khuyến khích học tập là gì?", "s-multi", ref_date="2026-10-20")
        self.assertFalse(first.refused)
        for query in ("Mức tiền nhận được là bao nhiêu?", "Thủ tục nhận thế nào?"):
            with self.subTest(query=query):
                followup = self.engine.ask(query, "s-multi", ref_date="2026-10-20")
                self.assertFalse(followup.refused, followup.answer)
                self.assertEqual(followup.references[0].rid, first.references[0].rid)

        unrelated = self.engine.ask("Thế còn wifi?", "s-multi", ref_date="2026-10-20")
        self.assertTrue(unrelated.refused)

    def test_build_card_syncs_llm_inline_citations_and_strips_duplicates(self):
        refs = [
            Reference(rid="r1", reg_title="QC1", aid="Điều 1", art_heading="H1", clause_ids=["1"], excerpt="Điểm trung bình từ 3.2"),
            Reference(rid="r2", reg_title="QC2", aid="Điều 2", art_heading="H2", clause_ids=["1"], excerpt="Thời gian bảo lưu 4 học kỳ"),
        ]
        card = build_card(
            "Bảo lưu tối đa 4 học kỳ [2].\n\nNgoài ra cần GPA từ 3.2 [1] [99].",
            refs, [], 0.9, llm_rewritten=True,
        )
        segs = card["verdict_segments"]
        self.assertEqual(len(segs), 2)
        self.assertEqual(segs[0]["cites"], [2])
        self.assertNotIn("[2]", segs[0]["text"])
        self.assertEqual(segs[1]["cites"], [1])
        self.assertNotIn("[1]", segs[1]["text"])
        self.assertNotIn("[99]", segs[1]["text"])

    def test_gemini_llm_uses_low_thinking_level_and_higher_output_budget(self):
        llm = GroundedLLM(AppConfig(llm_backend="gemini", gemini_key="synthetic-key", gemini_model="gemini-3.8-flash"))
        ref = Reference(rid="r1", reg_title="QC", aid="Điều 1", art_heading="H", clause_ids=["1"], excerpt="Tối đa 4 học kỳ.")
        fake_resp = MagicMock()
        fake_resp.__enter__.return_value.read.return_value = json.dumps({
            "candidates": [{
                "content": {
                    "parts": [
                        {"thought": True, "text": "internal thought"},
                        {"text": "Tối đa 4 học kỳ [1]."},
                    ],
                },
            }],
        }).encode()
        with patch("core.llm.urllib.request.urlopen", return_value=fake_resp) as req_mock:
            out = llm.rewrite(
                "Bảo lưu bao lâu?", "Tối đa 4 học kỳ.", [ref],
                history_summary=[{"question": "Điều kiện bảo lưu?", "answer": "Hoàn thành 1 kỳ."}],
            )
        self.assertEqual(out, "Tối đa 4 học kỳ [1].")
        sent = json.loads(req_mock.call_args.args[0].data)
        self.assertEqual(sent["generationConfig"]["maxOutputTokens"], 1200)
        self.assertEqual(sent["generationConfig"]["thinkingConfig"], {"thinkingLevel": "low"})
        self.assertIn("LỊCH SỬ GẦN ĐÂY", sent["contents"][0]["parts"][0]["text"])

    def test_cloud_embedding_adapter_caches_normalized_vectors(self):
        cfg = AppConfig(semantic_enabled=True, embedding_backend="gemini", gemini_key="synthetic-key")
        encoder = SemanticEncoder("unused-local", self.root / "models", config=cfg)

        def fake_urlopen(req, timeout=30):
            payload = json.loads(req.data.decode("utf-8"))
            count = len(payload["requests"])
            resp = MagicMock()
            resp.__enter__.return_value.read.return_value = json.dumps({
                "embeddings": [{"values": [3.0, 4.0, 0.0, 0.0]} for _ in range(count)],
            }).encode()
            return resp

        with patch("core.semantic.urllib.request.urlopen", side_effect=fake_urlopen) as mock_http:
            ok = encoder.build(["Đoạn 1", "Đoạn 2"], index_fingerprint="fp1")
            self.assertTrue(ok, encoder.error)
            self.assertEqual(encoder.provider_name, "gemini-embed")
            sims = encoder.similarities("Câu hỏi")
            self.assertEqual(len(sims), 2)
            self.assertAlmostEqual(sims[0], 1.0, places=4)
            # Second build hits disk cache (no extra passage HTTP call).
            calls_before = mock_http.call_count
            encoder2 = SemanticEncoder("unused-local", self.root / "models", config=cfg)
            self.assertTrue(encoder2.build(["Đoạn 1", "Đoạn 2"], index_fingerprint="fp1"))
            self.assertEqual(mock_http.call_count, calls_before)

    def test_history_display_limit_is_decoupled_from_rag_max_history(self):
        for i in range(12):
            resp = self.engine.ask(f"Điều kiện bảo lưu kết quả học tập là gì? ({i})", "s-long", ref_date="2026-10-20")
            self.assertFalse(resp.refused)
        all_rows = self.engine.history("s-long")
        self.assertEqual(len(all_rows), 12)
        first_page = self.engine.history("s-long", limit=5)
        self.assertEqual(len(first_page), 5)
        older_page = self.engine.history("s-long", limit=5, before_id=first_page[0]["id"])
        self.assertEqual(len(older_page), 5)
        self.assertLess(older_page[-1]["id"], first_page[0]["id"])


class NewPublicApiEndpointsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        cfg = AppConfig(semantic_enabled=False, api_token="synthetic-admin-secret")
        searcher = HybridSearcher(cfg)
        searcher.build([
            chunk for reg in build_corpus()
            for chunk in split_regulation(reg, 800, 1)
        ])
        with patch("core.engine.SESSION_DB", self.root / "sessions.db"), patch("core.engine.DOCS", self.root / "documents"):
            self.engine = HocVuEngine(cfg, searcher)
        self.voice = VoiceManager(audio_dir=self.root / "audio")
        self.patches = [
            patch.object(server, "engine", self.engine),
            patch.object(server, "config", cfg),
            patch.object(server, "requires_api_token", True),
            patch.object(server, "browser_auth_enabled", True),
            patch.object(server, "request_limiter", server.SlidingWindowLimiter()),
            patch.object(server, "get_voice_manager", return_value=self.voice),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app), base_url="http://test",
            headers={"Origin": "http://test"},
        )
        self.addAsyncCleanup(self.client.aclose)

    async def test_health_exposes_llm_stt_and_demo_flags(self):
        resp = await self.client.get("/api/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("llm_available", data)
        self.assertFalse(data["llm_available"])
        self.assertIn("stt_fallback", data)
        self.assertTrue(data["demo_only"])
        self.assertEqual(data["uploaded_documents"], 0)

    async def test_public_catalog_detail_is_sanitized_and_public(self):
        resp = await self.client.get("/api/catalog/QD-DTDC-HPU-2026")
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["rid"], "QD-DTDC-HPU-2026")
        self.assertGreater(len(body["articles"]), 0)
        for private_key in ("filename", "stored_name", "sha256", "ocr", "extracted_path"):
            self.assertNotIn(private_key, body)
        missing = await self.client.get("/api/catalog/NON-EXISTENT-ID")
        self.assertEqual(missing.status_code, 404)

    async def test_tts_stream_and_stt_fallback_endpoints(self):
        async def fake_chunks(*args, **kwargs):
            yield b"ID3-chunk-1"
            yield b"-chunk-2"

        with patch.object(self.voice, "stream_synthesize", side_effect=fake_chunks):
            resp = await self.client.post("/api/tts/stream", json={"text": "Xin chào", "rate": "+0%"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers["content-type"], "audio/mpeg")
        self.assertEqual(resp.content, b"ID3-chunk-1-chunk-2")

        # STT unconfigured returns 503.
        stt_off = await self.client.post("/api/stt", files={"file": ("voice.webm", b"webmdata", "audio/webm")})
        self.assertEqual(stt_off.status_code, 503)

        # STT oversized returns 400 when configured.
        with patch.object(server.config, "gemini_key", "synthetic-key"):
            too_big = await self.client.post(
                "/api/stt",
                files={"file": ("voice.webm", b"0" * (MAX_AUDIO_BYTES + 1), "audio/webm")},
            )
            self.assertEqual(too_big.status_code, 400)
            with patch.object(CloudSTT, "transcribe", return_value="Điều kiện bảo lưu?"):
                ok = await self.client.post(
                    "/api/stt",
                    files={"file": ("voice.webm", b"small-audio", "audio/webm")},
                )
            self.assertEqual(ok.status_code, 200)
            self.assertEqual(ok.json()["text"], "Điều kiện bảo lưu?")

    async def test_ask_stream_emits_evidence_and_done_sse_events(self):
        headers = {"Origin": "http://test", "X-HocVu-Owner": "a" * 64}
        resp = await self.client.post(
            "/api/ask/stream", headers=headers,
            json={"question": "Điều kiện bảo lưu kết quả học tập là gì?", "session_id": "sse-1", "ref_date": "2026-10-20"},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertIn("text/event-stream", resp.headers["content-type"])
        self.assertIn("event: evidence", resp.text)
        self.assertIn("event: done", resp.text)
        self.assertIn("Điều 5", resp.text)


if __name__ == "__main__":
    unittest.main()
