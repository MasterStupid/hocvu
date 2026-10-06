"""Dependency-free hybrid retriever for Vietnamese regulation text."""
from __future__ import annotations

import json
import math
import shutil
from collections import Counter
from datetime import date, datetime
from pathlib import Path

from .models import Chunk, RankedChunk
from .nlp import content_tokens
from .semantic import SemanticEncoder
from .settings import MODELS


INDEX_SCHEMA_VERSION = 2


class HybridSearcher:
    def __init__(self, config):
        self.config = config
        self.chunks: list[Chunk] = []
        self._freqs: list[Counter] = []
        self._idf: dict[str, float] = {}
        self._avg_len = 0.0
        self.semantic: SemanticEncoder | None = None
        self.semantic_error = ""

    @property
    def provider(self) -> str:
        return "bm25+multilingual-e5" if self.semantic and self.semantic.available else "bm25"

    def build(self, chunks: list[Chunk]) -> None:
        self.chunks = chunks
        token_lists = [content_tokens(chunk.text + " " + chunk.art_heading) for chunk in chunks]
        self._freqs = [Counter(tokens) for tokens in token_lists]
        self._avg_len = sum(map(len, token_lists)) / max(1, len(token_lists))
        df = Counter(token for freq in self._freqs for token in freq)
        total = len(self.chunks)
        self._idf = {token: math.log(1 + (total - count + 0.5) / (count + 0.5)) for token, count in df.items()}
        if not self.config.semantic_enabled:
            self.semantic = None
            self.semantic_error = "Disabled by HV_SEMANTIC"
            return
        self.semantic = SemanticEncoder(self.config.embedding_model, MODELS)
        passages = [f"{chunk.art_heading}\n{chunk.text}" for chunk in chunks]
        if not self.semantic.build(passages):
            self.semantic_error = self.semantic.error

    def save(self, path: str) -> None:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".tmp")
        temporary.write_text(json.dumps({
            "schema_version": INDEX_SCHEMA_VERSION,
            "chunks": [chunk.to_dict() for chunk in self.chunks],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        if destination.exists():
            shutil.copy2(destination, destination.with_suffix(".json.bak"))
        temporary.replace(destination)

    @classmethod
    def load(cls, path: str, config):
        def read_index(index_path: Path):
            try:
                return json.loads(index_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError("Index bị lỗi hoặc không đọc được. Hãy chạy lại 'python manage.py ingest'.") from exc

        index_path = Path(path)
        try:
            data = read_index(index_path)
        except ValueError:
            backup = index_path.with_suffix(".json.bak")
            if not backup.exists():
                raise
            data = read_index(backup)
        schema_version = data.get("schema_version", 1)
        if schema_version not in {1, INDEX_SCHEMA_VERSION}:
            raise ValueError(f"Index schema version {schema_version} không được hỗ trợ. Hãy chạy lại 'python manage.py ingest'.")
        if not isinstance(data.get("chunks"), list):
            raise ValueError("Index không hợp lệ: thiếu danh sách chunks. Hãy chạy lại 'python manage.py ingest'.")
        try:
            chunks = [Chunk.from_dict(item) for item in data.get("chunks", [])]
        except (KeyError, TypeError) as exc:
            raise ValueError("Index không tương thích với phiên bản hiện tại. Hãy chạy lại 'python manage.py ingest'.") from exc
        searcher = cls(config)
        searcher.build(chunks)
        return searcher

    def search(self, query: str, top_k: int | None = None, ref_date: str | None = None) -> list[RankedChunk]:
        if not self.chunks:
            return []
        q_tokens = content_tokens(query)
        if not q_tokens:
            return []
        q_freq = Counter(q_tokens)
        try:
            semantic_scores = self.semantic.similarities(query) if self.semantic and self.semantic.available else []
        except Exception as exc:
            # A runtime model/CPU error must degrade to BM25 instead of
            # dropping the user's request.
            self.semantic_error = f"Semantic query fallback: {type(exc).__name__}: {exc}"
            self.semantic = None
            semantic_scores = []
        lexical_scores: list[float] = []
        candidates = []
        k1, b = 1.5, 0.75
        for index, (chunk, freq) in enumerate(zip(self.chunks, self._freqs)):
            if not self._is_valid(chunk, ref_date):
                continue
            length = sum(freq.values())
            bm25 = 0.0
            for token, q_count in q_freq.items():
                term_freq = freq.get(token, 0)
                if term_freq:
                    bm25 += self._idf.get(token, 0.0) * (term_freq * (k1 + 1) / (term_freq + k1 * (1 - b + b * length / max(1, self._avg_len))) * min(q_count, 2))
            heading_terms = set(content_tokens(chunk.art_heading))
            bm25 += sum(self._idf.get(token, 0.0) * 2.0 for token in q_freq if token in heading_terms)
            normalized_query = " ".join(q_tokens)
            normalized_text = " ".join(content_tokens(chunk.text))
            if len(q_tokens) > 1 and normalized_query in normalized_text:
                bm25 += 3.0
            candidates.append((index, chunk, bm25))
            lexical_scores.append(bm25)

        if not candidates:
            return []
        lexical_peak = max(lexical_scores) or 1.0
        results: list[RankedChunk] = []
        for index, chunk, bm25 in candidates:
            vec = semantic_scores[index] if semantic_scores else 0.0
            # Blend normalized lexical relevance with cosine semantic
            # relevance. BM25 remains the complete fallback when the local
            # model is unavailable, so existing deployments do not regress.
            score = (
                self.config.bm25_weight * (bm25 / lexical_peak)
                + (1 - self.config.bm25_weight) * max(0.0, vec)
            ) if semantic_scores else bm25
            results.append(RankedChunk(chunk=chunk, score=score, bm25=bm25, vec=vec))
        results.sort(key=lambda item: item.score, reverse=True)
        return results[: top_k or self.config.top_k]

    @staticmethod
    def lexical_coverage(query: str, hit: RankedChunk) -> float:
        """Fraction of meaningful query terms directly supported by a hit.

        Raw BM25 values depend on corpus size and cannot be used as a global
        confidence scale. Coverage is stable and lets the engine abstain from
        a document that merely shares one generic word with a long query.
        """
        query_terms = set(content_tokens(query))
        if not query_terms:
            return 0.0
        evidence_terms = set(content_tokens(f"{hit.chunk.art_heading} {hit.chunk.text}"))
        return len(query_terms & evidence_terms) / len(query_terms)

    @staticmethod
    def _is_valid(chunk: Chunk, ref_date: str | None) -> bool:
        if not ref_date:
            return True
        try:
            at = datetime.strptime(ref_date, "%Y-%m-%d").date()
            start = datetime.strptime(chunk.valid_from, "%Y-%m-%d").date() if chunk.valid_from else date.min
            end = datetime.strptime(chunk.valid_until, "%Y-%m-%d").date() if chunk.valid_until else date.max
            return start <= at <= end
        except ValueError:
            # Invalid metadata must never make a document appear valid.
            return False
