"""Embedding persistence without loading or downloading a transformer model."""
import builtins
import hashlib
import io
import sys
import tempfile
import threading
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

try:
    import numpy as np
except ImportError:
    np = None

from core.engine import HocVuEngine, build_index
from core.index_version import INDEX_SOURCE_FILES
from core.searcher import HybridSearcher
from core.semantic import SemanticEncoder
from core.settings import AppConfig


class FakeModel:
    calls = []

    def __init__(self, *args, **kwargs):
        pass

    def get_sentence_embedding_dimension(self):
        return 4

    def encode(self, texts, **kwargs):
        self.calls.append(list(texts))
        vectors = np.array([
            list(hashlib.sha256(text.encode()).digest()[:4]) for text in texts
        ], dtype=np.float32) + 1
        return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)


@unittest.skipIf(np is None, "NumPy is optional in BM25-only installations")
class SemanticCacheTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.models = self.root / "models"
        self.index = self.root / "index.json"
        self.passages = ["Quy định học phí", "Điều kiện tốt nghiệp"]
        self.config = AppConfig(semantic_enabled=True)
        FakeModel.calls = []
        self.sources = []
        for source in INDEX_SOURCE_FILES:
            copy = self.root / source.name
            copy.write_bytes(source.read_bytes())
            self.sources.append(copy)
        for patcher in (
            patch.dict(sys.modules, sentence_transformers=types.SimpleNamespace(
                SentenceTransformer=FakeModel,
            )),
            patch("core.searcher.MODELS", self.models),
            patch("core.index_version.INDEX_SOURCE_FILES", tuple(self.sources)),
            patch("core.engine.DOCS", self.root / "documents"),
            patch("core.engine.SESSION_DB", self.root / "sessions.db"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def build(self, passages=None, model="test-e5", fingerprint="rules"):
        encoder = SemanticEncoder(model, self.models)
        self.assertTrue(encoder.build(
            self.passages if passages is None else passages,
            index_fingerprint=fingerprint,
        ), encoder.error)
        return encoder

    def cache_file(self):
        return next((self.models / "embeddings").glob("*.npz"))

    def test_saved_vectors_are_reused_and_queries_still_encode(self):
        first = self.build()
        expected = first.similarities("Tốt nghiệp?")
        FakeModel.calls.clear()
        second = self.build()
        self.assertEqual(FakeModel.calls, [])
        np.testing.assert_array_equal(first.embeddings, second.embeddings)
        self.assertEqual(expected, second.similarities("Tốt nghiệp?"))
        self.assertEqual(FakeModel.calls, [["query: Tốt nghiệp?"]])

    def test_passage_content_order_count_model_and_fingerprint_invalidate(self):
        self.build()
        for kwargs in (
            {"passages": ["Nội dung mới", self.passages[1]]},
            {"passages": list(reversed(self.passages))},
            {"passages": self.passages[:1]},
            {"model": "other-model"},
            {"fingerprint": "new-chunking"},
        ):
            with self.subTest(kwargs=kwargs):
                FakeModel.calls.clear()
                self.build(**kwargs)
                self.assertEqual(len(FakeModel.calls), 1)
                FakeModel.calls.clear()
                self.build(**kwargs)
                self.assertEqual(FakeModel.calls, [])

    def test_encoder_source_and_library_versions_invalidate(self):
        self.build()
        with patch("core.semantic.version", return_value="new-library"):
            self.build()
        with patch("core.semantic.Path.read_bytes", return_value=b"new encoding rules"):
            self.build()
        self.assertEqual(len(FakeModel.calls), 3)

    def test_corrupt_or_incompatible_caches_rebuild_once(self):
        encoder = self.build()
        cache = self.cache_file()
        with np.load(cache, allow_pickle=False) as saved:
            key = saved["key"].item()
        valid = encoder.embeddings
        variants = [
            {"key": "old-key", "embeddings": valid},
            {"key": key, "embeddings": valid[:1]},
            {"key": key, "embeddings": valid[:, :2]},
            {"key": key, "embeddings": valid.reshape(-1)},
            {"key": key, "embeddings": np.full((2, 4), np.nan)},
            {"key": key, "embeddings": np.full((2, 4), np.inf)},
            {"key": key, "embeddings": np.zeros((2, 4))},
            {"key": key, "embeddings": np.ones((2, 4), dtype=int)},
            {"key": key, "embeddings": np.array([object()], dtype=object)},
            {"embeddings": valid},
        ]
        wrong_format = io.BytesIO()
        np.save(wrong_format, valid)
        for variant in [b"not an archive", cache.read_bytes()[:80], wrong_format.getvalue(), *variants]:
            with self.subTest(variant=str(variant)[:80]):
                if isinstance(variant, bytes):
                    cache.write_bytes(variant)
                else:
                    np.savez(cache, **variant)
                FakeModel.calls.clear()
                self.build()
                self.build()
                self.assertEqual(len(FakeModel.calls), 1)

    def test_simultaneous_starts_encode_only_once(self):
        ready = threading.Barrier(2)

        def initialize(model, *args, **kwargs):
            ready.wait(timeout=10)

        with (
            patch.object(FakeModel, "__init__", initialize),
            ThreadPoolExecutor(max_workers=2) as workers,
        ):
            first, second = list(workers.map(lambda _: self.build(), range(2)))
        self.assertEqual(len(FakeModel.calls), 1)
        np.testing.assert_array_equal(first.embeddings, second.embeddings)

    def test_failed_atomic_save_keeps_existing_cache_and_reports_warning(self):
        encoder = self.build()
        cache = self.cache_file()
        original = cache.read_bytes()
        # Force a cache miss at the same destination without changing its bytes.
        with (
            patch.object(SemanticEncoder, "_read_cache", return_value=None),
            patch("core.index_storage.os.replace", side_effect=OSError("disk full")),
        ):
            rebuilt = self.build()
        self.assertTrue(rebuilt.available)
        self.assertIn("disk full", rebuilt.cache_error)
        self.assertEqual(cache.read_bytes(), original)
        self.assertEqual(list(cache.parent.glob("*.tmp")), [])
        np.testing.assert_array_equal(encoder.embeddings, rebuilt.embeddings)
        FakeModel.calls.clear()
        self.build()
        self.assertEqual(FakeModel.calls, [])

    def test_unwritable_cache_still_encodes_in_memory(self):
        self.models.mkdir()
        (self.models / "embeddings").write_text("not a directory")
        encoder = self.build()
        self.assertTrue(encoder.available)
        self.assertIn("Embedding cache unavailable", encoder.cache_error)

    def test_model_failure_keeps_explicit_bm25_fallback(self):
        self.build()
        with patch.object(FakeModel, "__init__", side_effect=RuntimeError("offline")):
            encoder = SemanticEncoder("test-e5", self.models)
            self.assertFalse(encoder.build(self.passages, index_fingerprint="rules"))
        self.assertFalse(encoder.available)
        self.assertIn("offline", encoder.error)

    def test_empty_collection_does_not_load_model(self):
        with patch.object(FakeModel, "__init__") as load:
            encoder = SemanticEncoder("test-e5", self.models)
            self.assertFalse(encoder.build([]))
        load.assert_not_called()

    def test_engine_and_direct_load_reuse_embeddings_without_reencoding(self):
        first = HocVuEngine.load_or_build(self.config, self.index)
        FakeModel.calls.clear()
        with patch("core.engine.build_index") as rebuild:
            second = HocVuEngine.load_or_build(self.config, self.index)
            direct = HybridSearcher.load(self.index, self.config)
        rebuild.assert_not_called()
        self.assertEqual(FakeModel.calls, [])
        self.assertEqual(second.searcher.provider, "bm25+multilingual-e5")
        np.testing.assert_array_equal(first.searcher.semantic.embeddings, direct.semantic.embeddings)
        # Explicit ingest also reuses embeddings if the corpus has not changed.
        build_index(self.config, index_path=self.index)
        self.assertEqual(FakeModel.calls, [])

    def test_freshness_and_chunk_settings_invalidate_even_if_passages_match(self):
        HocVuEngine.load_or_build(self.config, self.index)
        for source in self.sources:
            with self.subTest(source=source.name):
                source.write_bytes(source.read_bytes() + b"\n# Changed source\n")
                FakeModel.calls.clear()
                HocVuEngine.load_or_build(self.config, self.index)
                HocVuEngine.load_or_build(self.config, self.index)
                self.assertEqual(len(FakeModel.calls), 1)
        for config in (
            replace(self.config, overlap_sents=0),
            replace(self.config, max_chunk_chars=120),
            replace(self.config, embedding_model="different-model"),
        ):
            with self.subTest(config=config):
                FakeModel.calls.clear()
                HocVuEngine.load_or_build(config, self.index)
                HocVuEngine.load_or_build(config, self.index)
                self.assertEqual(len(FakeModel.calls), 1)

    def test_new_regulation_text_invalidates_and_query_settings_do_not(self):
        HocVuEngine.load_or_build(self.config, self.index)
        FakeModel.calls.clear()
        HocVuEngine.load_or_build(replace(self.config, top_k=99, bm25_weight=0.3), self.index)
        self.assertEqual(FakeModel.calls, [])
        searcher = HybridSearcher.load(self.index, self.config)
        searcher.chunks[0].text += "\nQuy định mới."
        changed = HybridSearcher(self.config)
        changed.build(searcher.chunks)
        changed.save(self.index)
        HybridSearcher.load(self.index, self.config)
        self.assertEqual(len(FakeModel.calls), 1)


class BM25OnlyCacheTests(unittest.TestCase):
    def test_no_semantic_imports_or_cache_access_with_semantic_disabled(self):
        original_import = builtins.__import__

        def guarded_import(name, *args, **kwargs):
            if name.split(".")[0] in {"numpy", "sentence_transformers", "torch", "transformers"}:
                self.fail(f"BM25 tried to import {name}")
            return original_import(name, *args, **kwargs)

        with (
            tempfile.TemporaryDirectory() as root,
            patch("builtins.__import__", side_effect=guarded_import),
            patch("core.searcher.SemanticEncoder") as encoder,
        ):
            searcher = HybridSearcher(AppConfig(semantic_enabled=False))
            searcher.build([])
            searcher.save(Path(root) / "index.json")
            restored = HybridSearcher.load(Path(root) / "index.json", searcher.config)
        encoder.assert_not_called()
        self.assertEqual(restored.provider, "bm25")
