"""Optional local semantic embeddings for Vietnamese document retrieval.

The application remains usable without this module's third-party dependency:
when Sentence Transformers or the model cannot be loaded, callers keep the
BM25 retriever.  This makes first-run and offline behaviour explicit instead
of silently producing a fake vector score.
"""
from __future__ import annotations

import hashlib
import io
import json
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from zipfile import BadZipFile

from .index_storage import atomic_write, index_write_lock


DEFAULT_MODEL = "intfloat/multilingual-e5-small"


class SemanticEncoder:
    """Small-corpus cosine search backed by a multilingual E5 embedding model."""

    def __init__(self, model_name: str, cache_dir: Path):
        self.model_name = model_name
        self.cache_dir = cache_dir
        self.model = None
        self.embeddings = None
        self.error = ""
        self.cache_error = ""

    @property
    def available(self) -> bool:
        return self.model is not None and self.embeddings is not None

    def _cache_key(self, passages: list[str], index_fingerprint: str | None) -> str:
        libraries = {}
        for package in ("sentence-transformers", "transformers", "torch"):
            try:
                libraries[package] = version(package)
            except PackageNotFoundError:
                libraries[package] = None
        # Include encoder source so prefix, normalization, or encoding changes
        # invalidate automatically, just like changes to chunk generation.
        payload = {
            "encoder_source": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "model": self.model_name,
            "libraries": libraries,
            "index_fingerprint": index_fingerprint,
            "passages": passages,
        }
        return hashlib.sha256(json.dumps(
            payload, ensure_ascii=False, sort_keys=True,
        ).encode("utf-8")).hexdigest()

    def _valid_embeddings(self, embeddings, count: int) -> bool:
        import numpy as np

        return (
            embeddings.ndim == 2
            and embeddings.shape == (count, self.model.get_sentence_embedding_dimension())
            and embeddings.dtype.kind == "f"
            and np.isfinite(embeddings).all()
            and np.allclose(np.linalg.norm(embeddings, axis=1), 1, atol=1e-3)
        )

    def _read_cache(self, path: Path, key: str, count: int):
        import numpy as np

        try:
            # Never allow pickle/object deserialization from a runtime cache.
            # Own the stream as well: malformed archive headers can fail
            # before NumPy's archive context manager has been entered.
            with path.open("rb") as stream:
                with np.load(stream, allow_pickle=False) as saved:
                    if saved["key"].item() != key:
                        return None
                    embeddings = saved["embeddings"]
            if self._valid_embeddings(embeddings, count):
                return embeddings
        except (OSError, ValueError, TypeError, KeyError, EOFError, BadZipFile):
            pass  # Missing, old, or corrupt caches are disposable.
        return None

    def _encode_passages(self, passages: list[str]):
        # E5 is trained for asymmetric retrieval. Preserve the same prefixes
        # and normalization for both fresh and cached passage embeddings.
        embeddings = self.model.encode(
            [f"passage: {passage}" for passage in passages],
            normalize_embeddings=True, convert_to_numpy=True,
            show_progress_bar=False,
        )
        if not self._valid_embeddings(embeddings, len(passages)):
            raise ValueError("Model returned invalid passage embeddings")
        return embeddings

    def build(self, passages: list[str], *, index_fingerprint: str | None = None) -> bool:
        self.model = self.embeddings = None
        self.error = self.cache_error = ""
        if not passages:
            self.error = "No passages to encode"
            return False
        try:
            import numpy as np
            from sentence_transformers import SentenceTransformer

            self.cache_dir.mkdir(parents=True, exist_ok=True)
            self.model = SentenceTransformer(self.model_name, cache_folder=str(self.cache_dir))
            key = self._cache_key(passages, index_fingerprint)
            destination = self.cache_dir / "embeddings" / f"{key}.npz"
            try:
                destination.parent.mkdir(parents=True, exist_ok=True)
                # Recheck under the lock: simultaneous server/CLI starts
                # should encode a given collection only once.
                with index_write_lock(destination):
                    self.embeddings = self._read_cache(destination, key, len(passages))
                    if self.embeddings is None:
                        self.embeddings = self._encode_passages(passages)
                        buffer = io.BytesIO()
                        np.savez(buffer, key=key, embeddings=self.embeddings)
                        atomic_write(destination, buffer.getvalue())
            except OSError as exc:
                # Cache persistence is optional, but expose failures rather
                # than silently disabling otherwise working semantic search.
                self.cache_error = f"Embedding cache unavailable: {type(exc).__name__}: {exc}"
                if self.embeddings is None:
                    self.embeddings = self._encode_passages(passages)
            return True
        except Exception as exc:  # dependency, download, or model-load error
            self.model = None
            self.embeddings = None
            self.error = f"{type(exc).__name__}: {exc}"
            return False

    def similarities(self, question: str) -> list[float]:
        if not self.available:
            return []
        query = self.model.encode(
            [f"query: {question}"], normalize_embeddings=True,
            convert_to_numpy=True, show_progress_bar=False,
        )[0]
        # Embeddings are unit-normalized, so a dot product is cosine similarity.
        return [float(score) for score in self.embeddings @ query]
