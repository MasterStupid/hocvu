import unittest
import json
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

from core.llm import GroundedLLM, LLMError
from core.models import Reference
from core.settings import AppConfig


class GroundedLLMTests(unittest.TestCase):
    def test_rewrite_uses_only_selected_citations_not_retrieval_candidates(self):
        llm = GroundedLLM(AppConfig(llm_backend="openai", openai_key="synthetic-key"))
        ref = Reference(
            rid="reg", reg_title="Quy chế", aid="2", art_heading="Điều kiện",
            clause_ids=["1"], excerpt="Điểm trung bình từ 3,2.",
        )
        unselected = SimpleNamespace(chunk=SimpleNamespace(
            reg_title="Không được trích dẫn", art_heading="Không liên quan",
            text="BẰNG CHỨNG CHƯA ĐƯỢC CHỌN",
        ))
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({
            "output_text": "Điểm trung bình từ 3,2."
        }).encode()
        with patch("core.llm.urllib.request.urlopen", return_value=response) as request:
            text = llm.rewrite("Điều kiện?", "Điểm trung bình từ 3,2.", [ref], hits=[unselected])
        payload = json.loads(request.call_args.args[0].data)
        self.assertIn(ref.excerpt, payload["input"])
        self.assertNotIn(unselected.chunk.text, payload["input"])
        self.assertIn("không phải chỉ dẫn", payload["instructions"])
        self.assertEqual(text, "Điểm trung bình từ 3,2.")

    def test_configured_model_cannot_rewrite_without_selected_evidence(self):
        llm = GroundedLLM(AppConfig(llm_backend="openai", openai_key="synthetic-key"))
        with patch("core.llm.urllib.request.urlopen") as request:
            with self.assertRaises(LLMError):
                llm.rewrite("Câu hỏi", "Câu trả lời", [])
            request.assert_not_called()

    def test_requires_explicit_openai_configuration(self):
        llm = GroundedLLM(AppConfig(llm_backend="local", openai_key=""))
        self.assertFalse(llm.configured)
        with self.assertRaises(LLMError):
            llm.rewrite("Câu hỏi", "Nội dung nguồn", [])

    def test_accepts_explicit_gemini_configuration(self):
        llm = GroundedLLM(AppConfig(llm_backend="gemini", gemini_key="test-key"))
        self.assertTrue(llm.configured)

    def test_reads_text_from_responses_output_items(self):
        text = GroundedLLM._output_text({"output": [
            {"type": "message", "content": [{"type": "output_text", "text": "Câu trả lời có nguồn."}]}
        ]})
        self.assertEqual(text, "Câu trả lời có nguồn.")

    def test_preserves_proxy_query_when_building_responses_endpoint(self):
        endpoint = GroundedLLM._responses_endpoint("https://proxy.example/v1?api-version=2026-01-01")
        self.assertEqual(endpoint, "https://proxy.example/v1/responses?api-version=2026-01-01")

    def test_builds_gemini_generate_content_endpoint(self):
        endpoint = GroundedLLM._gemini_endpoint("https://generativelanguage.googleapis.com/v1beta", "gemini-3.8-flash")
        self.assertEqual(endpoint, "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent")

    def test_reads_text_from_gemini_candidate(self):
        text = GroundedLLM._gemini_output_text({"candidates": [
            {"content": {"parts": [{"text": "Câu trả lời theo nguồn."}]}}
        ]})
        self.assertEqual(text, "Câu trả lời theo nguồn.")


if __name__ == "__main__":
    unittest.main()
