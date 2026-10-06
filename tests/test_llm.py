import unittest

from core.llm import GroundedLLM, LLMError
from core.settings import AppConfig


class GroundedLLMTests(unittest.TestCase):
    def test_requires_explicit_openai_configuration(self):
        llm = GroundedLLM(AppConfig(llm_backend="local", openai_key=""))
        self.assertFalse(llm.configured)
        with self.assertRaises(LLMError):
            llm.rewrite("Câu hỏi", "Nội dung nguồn", [])

    def test_reads_text_from_responses_output_items(self):
        text = GroundedLLM._output_text({"output": [
            {"type": "message", "content": [{"type": "output_text", "text": "Câu trả lời có nguồn."}]}
        ]})
        self.assertEqual(text, "Câu trả lời có nguồn.")

    def test_preserves_proxy_query_when_building_responses_endpoint(self):
        endpoint = GroundedLLM._responses_endpoint("https://proxy.example/v1?api-version=2026-01-01")
        self.assertEqual(endpoint, "https://proxy.example/v1/responses?api-version=2026-01-01")


if __name__ == "__main__":
    unittest.main()
