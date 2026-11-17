import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from core.encoder import OpenAIEncoder, SimHashEncoder, build_encoder
from core.settings import AppConfig


class OpenAIEncoderTests(unittest.TestCase):
    def test_base_and_complete_endpoint_urls_resolve_to_embeddings_once(self):
        for base, expected in (
            (None, "https://api.openai.com/v1/embeddings"),
            ("https://api.openai.com/v1/", "https://api.openai.com/v1/embeddings"),
            ("https://gateway.example/custom/v1", "https://gateway.example/custom/v1/embeddings"),
            ("http://localhost:9000/v1/embeddings/", "http://localhost:9000/v1/embeddings"),
        ):
            self.assertEqual(OpenAIEncoder("synthetic-key", api_url=base).api_url, expected)

    def test_build_encoder_uses_the_configured_base_and_request_dimensions(self):
        config = AppConfig(
            llm_backend="openai", openai_key="synthetic-key", embed_dim=2,
            openai_url="https://gateway.example/v1",
        )
        encoder = build_encoder(config)
        response = io.BytesIO(json.dumps({"data": [
            {"index": 1, "embedding": [0.3, 0.4]},
            {"index": 0, "embedding": [0.1, 0.2]},
        ]}).encode())
        with patch("urllib.request.urlopen", return_value=response) as request:
            vectors = encoder.encode_batch(["first", "second"])
        self.assertEqual(vectors, [[0.1, 0.2], [0.3, 0.4]])
        self.assertEqual(request.call_args.args[0].full_url, "https://gateway.example/v1/embeddings")
        payload = json.loads(request.call_args.kwargs["data"])
        self.assertEqual(payload["dimensions"], 2)
        self.assertEqual(payload["input"], ["first", "second"])
        self.assertEqual(request.call_args.kwargs["timeout"], 35)

    def test_custom_models_do_not_receive_unsupported_dimensions_parameter(self):
        encoder = OpenAIEncoder("synthetic-key", model="custom", dim=2)
        response = io.BytesIO(b'{"data":[{"index":0,"embedding":[1,2]}]}')
        with patch("urllib.request.urlopen", return_value=response) as request:
            self.assertEqual(encoder.encode("test"), [1, 2])
        self.assertNotIn("dimensions", json.loads(request.call_args.kwargs["data"]))

    def test_request_failures_are_explicit_and_never_return_zero_vectors(self):
        for error in (
            HTTPError("https://gateway.example", 404, "Not Found", {}, None),
            TimeoutError("Timed out"),
        ):
            with patch("urllib.request.urlopen", side_effect=error):
                with self.assertRaisesRegex(RuntimeError, "no vectors"):
                    OpenAIEncoder("synthetic-key").encode_batch(["test"])

    def test_invalid_response_shape_indices_and_vectors_are_rejected(self):
        for data in (
            [], [{"index": 1, "embedding": [1, 2]}],
            [{"index": 0, "embedding": [1]}],
            [{"index": 0, "embedding": [0, 0]}],
            [{"index": 0, "embedding": [float("nan"), 1]}],
            [{"index": 0, "embedding": [True, 1]}],
        ):
            response = io.BytesIO(json.dumps({"data": data}).encode())
            with patch("urllib.request.urlopen", return_value=response):
                with self.assertRaises(RuntimeError):
                    OpenAIEncoder("synthetic-key", dim=2).encode("test")

    def test_empty_batch_never_calls_network(self):
        with patch("urllib.request.urlopen") as request:
            self.assertEqual(OpenAIEncoder("synthetic-key").encode_batch([]), [])
            request.assert_not_called()

    def test_missing_or_sample_keys_do_not_enable_network_encoder(self):
        for key in ("", "  ", "your-api-key-here"):
            config = AppConfig(llm_backend="openai", openai_key=key)
            self.assertIsInstance(build_encoder(config), SimHashEncoder)
            with self.assertRaises(ValueError):
                OpenAIEncoder(key)
