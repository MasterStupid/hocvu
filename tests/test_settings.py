import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.settings import AppConfig, ROOT, _load_dotenv, load_config
from core.llm import GroundedLLM, LLMError


class ConfigurationSafetyTests(unittest.TestCase):
    def test_negative_overlap_is_rejected_but_zero_and_large_values_are_valid(self):
        with patch.dict(os.environ, {"HV_OVERLAP_SENTS": "-1"}, clear=True):
            with self.assertRaisesRegex(ValueError, "overlap_sents"):
                load_config()
        for value in ("0", "100000"):
            with patch.dict(os.environ, {"HV_OVERLAP_SENTS": value}, clear=True):
                self.assertEqual(load_config().overlap_sents, int(value))

    def test_copying_example_without_keys_does_not_configure_either_provider(self):
        with tempfile.TemporaryDirectory() as temporary:
            example = Path(temporary) / ".env"
            example.write_text((ROOT / ".env.example").read_text(), encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                _load_dotenv(example)
                config = load_config()
                self.assertEqual(config.openai_key, "")
                self.assertEqual(config.gemini_key, "")
                for backend in ("openai", "gemini"):
                    config.llm_backend = backend
                    self.assertFalse(GroundedLLM(config).configured)

    def test_old_placeholders_and_whitespace_never_trigger_llm_requests(self):
        for backend, name, placeholder in (
            ("openai", "OPENAI_API_KEY", "your-api-key-here"),
            ("gemini", "GEMINI_API_KEY", "your-gemini-api-key-here"),
        ):
            for value in (placeholder, "  "):
                with self.subTest(backend=backend, value=value):
                    with patch.dict(os.environ, {"HV_LLM": backend, name: value}, clear=True):
                        config = load_config()
                    self.assertFalse(GroundedLLM(config).configured)
                    # Direct dataclass callers must receive the same protection.
                    direct = AppConfig(llm_backend=backend, **{backend + "_key": value})
                    with patch("urllib.request.urlopen") as request:
                        with self.assertRaises(LLMError):
                            GroundedLLM(direct).rewrite("question", "answer", [])
                        request.assert_not_called()

    def test_provider_key_formats_are_not_assumed(self):
        config = AppConfig(llm_backend="openai", openai_key="synthetic-gateway-token")
        self.assertTrue(GroundedLLM(config).configured)


class SettingsTests(unittest.TestCase):
    def test_example_defaults_match_runtime_defaults(self):
        # Test defaults independently of the hosting environment's overrides.
        with patch.dict(os.environ):
            for name in (
                "HV_TOP_K", "HV_BM25_WEIGHT", "HV_SEMANTIC_FLOOR",
                "HV_LEXICAL_COVERAGE_FLOOR", "HV_SEMANTIC",
            ):
                os.environ.pop(name, None)
            config = load_config()
        self.assertEqual(config.top_k, 5)
        self.assertEqual(config.bm25_weight, 0.10)
        self.assertEqual(config.semantic_floor, 0.20)
        self.assertEqual(config.lexical_coverage_floor, 0.50)
        self.assertTrue(config.semantic_enabled)

    def test_invalid_environment_value_is_reported(self):
        with patch.dict(os.environ, {"HV_TOP_K": "not-a-number"}, clear=False):
            with self.assertRaisesRegex(ValueError, "HV_TOP_K"):
                load_config()

    def test_out_of_range_environment_value_is_reported(self):
        with patch.dict(os.environ, {"HV_BM25_WEIGHT": "2"}, clear=False):
            with self.assertRaisesRegex(ValueError, "bm25_weight"):
                load_config()


if __name__ == "__main__":
    unittest.main()
