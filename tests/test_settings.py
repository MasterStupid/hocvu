import os
import unittest
from unittest.mock import patch

from core.settings import load_config


class SettingsTests(unittest.TestCase):
    def test_example_defaults_match_runtime_defaults(self):
        config = load_config()
        self.assertEqual(config.top_k, 5)
        self.assertEqual(config.bm25_weight, 0.10)
        self.assertEqual(config.semantic_floor, 0.20)
        self.assertEqual(config.lexical_coverage_floor, 0.50)
        self.assertTrue(config.semantic_enabled)
        self.assertEqual(config.whisper_size, "small")

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
