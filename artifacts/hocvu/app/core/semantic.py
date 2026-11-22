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
import urllib.error
import urllib.request
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit
from zipfile import BadZipFile

from .index_storage import atomic_write, index_write_lock
from .settings import clean_api_key


DEFAULT_MODEL = "intfloat/multilingual-e5-small"


class _CloudEmbeddingModel:
    """Lightweight stdlib HTTP adapter for Gemini or OpenAI embeddings (no PyTorch)."""

    def __init__(self, provider: str, model_name: str, api_key: str, base_url: str):
        self.provider = provider
        self.model_name = model_name
        self.api_key = api_key
        self.base_url = base_url
        self._dim: int | None = None

    def get_sentence_embedding_dimension(self) -> int:
        return self._dim or 0

    def _normalize(self, raw_vectors: list[list[float]]):
        import numpy as np

        arr = np.asarray(raw_vectors, dtype=np.float32)
        if arr.ndim != 2 or arr.shape[0] == 0 or arr.shape[1] == 0:
            raise ValueError("Cloud embedding returned invalid matrix shape")
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)
        arr = arr / norms
        self._dim = int(arr.shape[1])
        return arr

    def encode(self, texts: list[str], *, task: str = "passage", **kwargs):
        if self.provider == "gemini":
            return self._encode_gemini(texts, task=task)
        return self._encode_openai(texts)

    def _encode_gemini(self, texts: list[str], *, task: str):
        task_type = "RETRIEVAL_QUERY" if task == "query" else "RETRIEVAL_DOCUMENT"
        parts = urlsplit(self.base_url)
        path = parts.path.rstrip("/")
        model_ref = f"models/{quote(self.model_name, safe='-._')}"
        endpoint = urlunsplit((parts.scheme, parts.netloc, f"{path}/{model_ref}:batchEmbedContents", parts.query, parts.fragment))
        vectors: list[list[float]] = []
        # Batch requests cleanly to stay under provider limits.
        for start in range(0, len(texts), 50):
            batch = texts[start:start + 50]
            payload = {
                "requests": [
                    {
                        "model": model_ref,
                        "taskType": task_type,
                        "content": {"parts": [{"text": text}]},
                    }
                    for text in batch
                ],
            }
            req = urllib.request.Request(
                endpoint,
                data=json.dumps(payload).encode("utf-8"),
                method="POST",
                headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=30) as response:
                body = json.loads(response.read().decode("utf-8"))
            for item in body.get("embeddings", []):
                values = item.get("values")
                if not isinstance(values, list):
                    raise ValueError("Missing values in Gemini embedding response")
                vectors.append(values)
        return self._normalize(vectors)

    def _encode_openai(self, texts: list[str]):
        parts = urlsplit(self.base_url)
        path = parts.path.rstrip("/")
        if not path.endswith("/embeddings"):
            path = f"{path}/embeddings"
        endpoint = urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))
        vectors: list[list[float]] = []
        for start in range(0, len(texts), 50):
            batch = texts[start:start + 50]
            payload = {"model": self.model_name, "input": batch}
            req = urllib.request.Request(
                endpoint,
                data=json.dumps(payload).encode("utf-8"),
                method="POST",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=30) as response:
                body = json.loads(response.read().decode("utf-8"))
            for item in sorted(body.get("data", []), key=lambda x: x.get("index", 0)):
                vectors.append(item["embedding"])
        return self._normalize(vectors)


class SemanticEncoder:
    """Small-corpus cosine search backed by local E5 or optional cloud embeddings."""

    def __init__(self, model_name: str, cache_dir: Path, config=None):
        self.model_name = model_name
        self.cache_dir = cache_dir
        self.config = config
        self.model = None
        self.embeddings = None
        self.provider_name = "multilingual-e5"
        self.error = ""
        self.cache_error = ""

    @property
    def available(self) -> bool:
        return self.model is not None and self.embeddings is not None

    def _active_model_id(self) -> str:
        if isinstance(self.model, _CloudEmbeddingModel):
            return f"{self.model.provider}:{self.model.model_name}"
        return self.model_name

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
            "model": self._active_model_id(),
            "libraries": libraries,
            "index_fingerprint": index_fingerprint,
            "passages": passages,
        }
        return hashlib.sha256(json.dumps(
            payload, ensure_ascii=False, sort_keys=True,
        ).encode("utf-8")).hexdigest()

    def _valid_embeddings(self, embeddings, count: int) -> bool:
        import numpy as np

        if embeddings.ndim != 2 or embeddings.shape[0] != count:
            return False
        expected_dim = self.model.get_sentence_embedding_dimension()
        dim_ok = (embeddings.shape[1] == expected_dim) if expected_dim > 0 else (embeddings.shape[1] > 0)
        return (
            dim_ok
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
                if isinstance(self.model, _CloudEmbeddingModel):
                    self.model._dim = int(embeddings.shape[1])
                return embeddings
        except (OSError, ValueError, TypeError, KeyError, EOFError, BadZipFile):
            pass  # Missing, old, or corrupt caches are disposable.
        return None

    def _encode_passages(self, passages: list[str]):
        if isinstance(self.model, _CloudEmbeddingModel):
            embeddings = self.model.encode(passages, task="passage")
        else:
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

    def _init_cloud_model(self, backend: str) -> _CloudEmbeddingModel | None:
        if self.config is None:
            return None
        gemini_key = clean_api_key(getattr(self.config, "gemini_key", ""))
        openai_key = clean_api_key(getattr(self.config, "openai_key", ""))
        if backend == "gemini" or (backend == "auto" and gemini_key):
            if not gemini_key:
                raise ValueError("GEMINI_API_KEY chưa được cấu hình cho embedding.")
            self.provider_name = "gemini-embed"
            return _CloudEmbeddingModel(
                "gemini", getattr(self.config, "gemini_embed", "gemini-embedding-001"),
                gemini_key, getattr(self.config, "gemini_url", "https://generativelanguage.googleapis.com/v1beta"),
            )
        if backend == "openai" or (backend == "auto" and openai_key):
            if not openai_key:
                raise ValueError("OPENAI_API_KEY chưa được cấu hình cho embedding.")
            self.provider_name = "openai-embed"
            return _CloudEmbeddingModel(
                "openai", getattr(self.config, "openai_embed", "text-embedding-3-small"),
                openai_key, getattr(self.config, "openai_url", "https://api.openai.com/v1"),
            )
        return None

    def build(self, passages: list[str], *, index_fingerprint: str | None = None) -> bool:
        self.model = self.embeddings = None
        self.error = self.cache_error = ""
        if not passages:
            self.error = "No passages to encode"
            return False
        backend = (getattr(self.config, "embedding_backend", "auto") or "auto").lower()
        try:
            import numpy as np

            self.cache_dir.mkdir(parents=True, exist_ok=True)
            if backend in {"gemini", "openai"}:
                self.model = self._init_cloud_model(backend)
            else:
                try:
                    from sentence_transformers import SentenceTransformer

                    self.provider_name = "multilingual-e5"
                    self.model = SentenceTransformer(self.model_name, cache_folder=str(self.cache_dir))
                except Exception as local_exc:
                    if backend == "auto":
                        cloud = self._init_cloud_model("auto")
                        if cloud is not None:
                            self.model = cloud
                        else:
                            raise local_exc
                    else:
                        raise local_exc

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
        if isinstance(self.model, _CloudEmbeddingModel):
            query = self.model.encode([question], task="query")[0]
        else:
            query = self.model.encode(
                [f"query: {question}"], normalize_embeddings=True,
                convert_to_numpy=True, show_progress_bar=False,
            )[0]
        # Embeddings are unit-normalized, so a dot product is cosine similarity.
        return [float(score) for score in self.embeddings @ query]
