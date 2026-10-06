"""Optional local semantic embeddings for Vietnamese document retrieval.

The application remains usable without this module's third-party dependency:
when Sentence Transformers or the model cannot be loaded, callers keep the
BM25 retriever.  This makes first-run and offline behaviour explicit instead
of silently producing a fake vector score.
"""
from __future__ import annotations

from pathlib import Path


DEFAULT_MODEL = "intfloat/multilingual-e5-small"


class SemanticEncoder:
    """Small-corpus cosine search backed by a multilingual E5 embedding model."""

    def __init__(self, model_name: str, cache_dir: Path):
        self.model_name = model_name
        self.cache_dir = cache_dir
        self.model = None
        self.embeddings = None
        self.error = ""

    @property
    def available(self) -> bool:
        return self.model is not None and self.embeddings is not None

    def build(self, passages: list[str]) -> bool:
        try:
            from sentence_transformers import SentenceTransformer

            self.cache_dir.mkdir(parents=True, exist_ok=True)
            self.model = SentenceTransformer(self.model_name, cache_folder=str(self.cache_dir))
            # E5 is trained for asymmetric retrieval: a short question looks
            # for a longer passage. Prefixes preserve that training signal.
            self.embeddings = self.model.encode(
                [f"passage: {passage}" for passage in passages],
                normalize_embeddings=True, convert_to_numpy=True,
                show_progress_bar=False,
            )
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
