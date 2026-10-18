"""Dependency-free hybrid retriever for Vietnamese regulation text."""
from __future__ import annotations

import json
import math
import re
import shutil
from collections import Counter
from datetime import date, datetime
from pathlib import Path

from .models import Chunk, RankedChunk
from .nlp import ACADEMIC_TOKEN_ALIASES, accent_key, accented_content_tokens, content_tokens, has_diacritics, normalize, strip_accents
from .semantic import SemanticEncoder
from .settings import MODELS


INDEX_SCHEMA_VERSION = 2


class StaleIndexError(ValueError):
    """The saved index was built with a different article-building version."""


class HybridSearcher:
    def __init__(self, config):
        self.config = config
        self.chunks: list[Chunk] = []
        self._freqs: list[Counter] = []
        self._lengths: list[int] = []
        self._idf: dict[str, float] = {}
        self._avg_len = 0.0
        self.semantic: SemanticEncoder | None = None
        self.semantic_error = ""

    @property
    def provider(self) -> str:
        return "bm25+multilingual-e5" if self.semantic and self.semantic.available else "bm25"

    def build(self, chunks: list[Chunk]) -> None:
        self.chunks = chunks
        # The splitter prepends the heading to every clause; index it once so
        # heading words are not counted twice on top of the heading boost.
        token_lists = [accented_content_tokens(f"{chunk.version} {chunk.reg_title} {chunk.art_heading} {self._clause_body(chunk)}") for chunk in chunks]
        # Each indexed word is counted under two forms: unaccented, for a
        # query typed without diacritics, and accent-sensitive, so that a
        # query typed with diacritics is not credited with (or diluted by)
        # different words that merely share an unaccented spelling.
        self._freqs = [Counter(self._index_forms(tokens)) for tokens in token_lists]
        self._lengths = [len(tokens) for tokens in token_lists]
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

    def save(self, path: str, article_version: str | None = None) -> None:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".tmp")
        temporary.write_text(json.dumps({
            "schema_version": INDEX_SCHEMA_VERSION,
            "article_version": article_version,
            "chunks": [chunk.to_dict() for chunk in self.chunks],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        if destination.exists():
            shutil.copy2(destination, destination.with_suffix(".json.bak"))
        temporary.replace(destination)

    @classmethod
    def load(cls, path: str, config, article_version: str | None = None):
        """Load a saved index.

        When ``article_version`` is given, an index recorded with a different
        (or no) version raises ``StaleIndexError`` before any embeddings are
        built, so the caller can rebuild instead.
        """
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
        if article_version is not None and data.get("article_version") != article_version:
            raise StaleIndexError(
                f"Index article version {data.get('article_version')!r} khác phiên bản hiện tại {article_version!r}."
            )
        if not isinstance(data.get("chunks"), list):
            raise ValueError("Index không hợp lệ: thiếu danh sách chunks. Hãy chạy lại 'python manage.py ingest'.")
        try:
            chunks = [Chunk.from_dict(item) for item in data.get("chunks", [])]
        except (KeyError, TypeError) as exc:
            raise ValueError("Index không tương thích với phiên bản hiện tại. Hãy chạy lại 'python manage.py ingest'.") from exc
        searcher = cls(config)
        searcher.build(chunks)
        return searcher

    def search(self, query: str, top_k: int | None = None, ref_date: str | None = None, include_expired: bool = False) -> list[RankedChunk]:
        if not self.chunks:
            return []
        q_tokens = content_tokens(query)
        if not q_tokens:
            return []
        q_freq = Counter(self._query_form(token) for token in accented_content_tokens(query))
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
            if not self._is_valid(chunk, ref_date, include_expired):
                continue
            length = self._lengths[index]
            bm25 = 0.0
            for token, q_count in q_freq.items():
                term_freq = freq.get(token, 0)
                if term_freq:
                    bm25 += self._idf.get(token, 0.0) * (term_freq * (k1 + 1) / (term_freq + k1 * (1 - b + b * length / max(1, self._avg_len))) * min(q_count, 2))
            heading_terms = set(self._index_forms(accented_content_tokens(f"{chunk.version} {chunk.reg_title} {chunk.art_heading}")))
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

    # Evidence checks compare words with their diacritics. Stripping accents
    # merges unrelated Vietnamese words ("bóng đá" vs "học bổng ... tối đa",
    # "hộ" vs "họ"), which must not count as support for an answer. A query
    # word typed without diacritics still matches on its unaccented form.

    @staticmethod
    def _term_forms(term: str) -> tuple[str, str]:
        """The accent-sensitive ("a:") and unaccented ("s:") forms of a word."""
        return f"a:{accent_key(term)}", f"s:{strip_accents(term)}"

    @staticmethod
    def _query_form(term: str) -> str:
        """Compare with diacritics only when the student typed them."""
        return f"a:{accent_key(term)}" if has_diacritics(term) else f"s:{term}"

    @classmethod
    def _index_forms(cls, tokens: list[str]) -> list[str]:
        return [form for token in tokens for form in cls._term_forms(token)]

    @classmethod
    def _phrase_index(cls, tokens: list[str]) -> set[tuple[str, str]]:
        return {
            (left, right)
            for first, second in zip(tokens, tokens[1:])
            for left in cls._term_forms(first)
            for right in cls._term_forms(second)
        }

    @staticmethod
    def _clause_body(chunk: Chunk) -> str:
        """Clause text without the article heading the splitter prepends."""
        text = chunk.text
        heading = (chunk.art_heading or "").strip()
        if heading and text.startswith(heading):
            return text[len(heading):].lstrip()
        return text

    @classmethod
    def _evidence_text(cls, chunk: Chunk) -> str:
        return f"{chunk.art_heading}\n{cls._clause_body(chunk)}"

    @staticmethod
    def _raw_words(text: str) -> list[str]:
        """Every lowercase word, stopwords included, for adjacency checks."""
        return re.findall(r"\w+", normalize(text).lower())

    @classmethod
    def _supported_terms(cls, query: str, chunk: Chunk) -> set[str]:
        """Query word forms that a clause (with its heading) states."""
        return cls._evidence_support(query, chunk)[0]

    @classmethod
    def _evidence_support(cls, query: str, chunk: Chunk) -> tuple[set[str], set[str]]:
        """Supported query word forms, and those that also anchor the topic.

        An abbreviation such as "ĐRL" stands for the whole phrase "điểm rèn
        luyện". It supports a query word only when the query uses at least
        two consecutive words of that phrase, so the syllable "điểm" of
        "điểm danh" is not credited to a clause that only mentions ĐRL.

        A supported word anchors the topic when its reading is unambiguous:
        it was typed with diacritics, or, typed without them, the clause also
        has it next to one of its neighbours in the question. A lone
        unaccented syllable is ambiguous ("bong" is both "bóng" and "bổng");
        the neighbour tells the readings apart ("giai bong da" never occurs
        in "học bổng ... tối đa"). Numbers never anchor a topic.
        """
        evidence = cls._evidence_text(chunk)
        tokens = accented_content_tokens(evidence, expand_aliases=False)
        words = set(cls._index_forms(tokens))
        alias_phrases: set[tuple[str, str]] = set()
        for token in tokens:
            expansion = ACADEMIC_TOKEN_ALIASES.get(strip_accents(token))
            if expansion:
                alias_phrases |= cls._phrase_index(list(expansion))
        sequence = [cls._query_form(term) for term in accented_content_tokens(query)]
        supported = {form for form in sequence if form in words}
        in_phrase: set[str] = set()
        for left, right in zip(sequence, sequence[1:]):
            if (left, right) in alias_phrases:
                supported.update((left, right))
                in_phrase.update((left, right))
        raw_sequence = [cls._query_form(word) for word in cls._raw_words(query)]
        if len(set(raw_sequence)) == 1:
            # A one-word question has no neighbour to disambiguate with.
            in_phrase |= supported
        else:
            # Adjacency is checked both on content words (so a stopword
            # between them does not matter) and on the raw wording (so a
            # neighbour that is a stopword, e.g. "bao" in "bao luu", counts).
            evidence_pairs = cls._phrase_index(tokens) | cls._phrase_index(cls._raw_words(evidence))
            for pairs in (zip(sequence, sequence[1:]), zip(raw_sequence, raw_sequence[1:])):
                in_phrase.update(form for pair in pairs if pair in evidence_pairs for form in pair)
        anchored = {
            form for form in supported
            if not form[2:].isdigit() and (form.startswith("a:") or form in in_phrase)
        }
        return supported, anchored

    @classmethod
    def _query_forms(cls, query: str) -> list[str]:
        return list(dict.fromkeys(cls._query_form(term) for term in accented_content_tokens(query)))

    @classmethod
    def lexical_coverage(cls, query: str, hit: RankedChunk | list[RankedChunk]) -> float:
        """Fraction of meaningful query terms directly supported by a hit.

        Raw BM25 values depend on corpus size and cannot be used as a global
        confidence scale. Coverage is stable and lets the engine abstain from
        a document that merely shares one generic word with a long query.
        """
        if isinstance(hit, list):
            return max((cls.lexical_coverage(query, item) for item in hit), default=0.0)
        query_forms = cls._query_forms(query)
        if not query_forms:
            return 0.0
        supported = cls._supported_terms(query, hit.chunk)
        return sum(form in supported for form in query_forms) / len(query_forms)

    @classmethod
    def phrase_coverage(cls, query: str, hit: RankedChunk) -> float:
        """Measure adjacent query terms for reranking only, never refusal."""
        query_tokens = cls._query_forms(query)
        query_phrases = set(zip(query_tokens, query_tokens[1:]))
        if not query_phrases:
            return 0.0
        evidence_phrases = cls._phrase_index(accented_content_tokens(cls._evidence_text(hit.chunk)))
        return len(query_phrases & evidence_phrases) / len(query_phrases)

    @classmethod
    def rerank_by_coverage(cls, query: str, hits: list[RankedChunk]) -> list[RankedChunk]:
        """Prefer the evidence that covers most of the student's question.

        BM25 remains the retrieval score; coverage is a transparent second
        stage that fixes a broad document winning over the exact clause.
        """
        peak_score = max((hit.score for hit in hits), default=0.0) or 1.0
        peak_bm25 = max((hit.bm25 for hit in hits), default=0.0) or 1.0
        query_terms = set(content_tokens(query))
        asks_for_conditions = {"dieu", "kien"}.issubset(query_terms)

        def rank(hit: RankedChunk) -> float:
            base_rel = (hit.score / peak_score) if hit.score > 0 else (hit.bm25 / peak_bm25)
            value = (
                (0.40 * cls.lexical_coverage(query, hit))
                + (0.30 * cls.phrase_coverage(query, hit))
                + (0.30 * base_rel)
            )
            if asks_for_conditions:
                evidence = hit.chunk.text.lower()
                if any(marker in evidence for marker in ("khi ", "từ ", "tối thiểu", "không được", "phải", "đủ điều kiện")):
                    value += 0.18
            return value
        return sorted(
            hits,
            key=rank,
            reverse=True,
        )

    # Written with diacritics so that, e.g., "dạ" (a polite particle) does not
    # also discard "đá"; unaccented query words compare on stripped forms.
    _generic_institutional_words = (
        "đại", "học", "trường", "sinh", "viên", "quy", "định", "văn", "bản",
        "tổ", "chức", "có", "cơ", "sở", "số", "yêu", "cầu", "bộ", "làm", "vào", "ở",
    )
    _conversational_words = ("em", "mình", "gặp", "xin", "ạ", "dạ")

    # Unaccented spellings of a non-specific word that are also meaningful
    # words: "da" is "dạ" (particle) but also "đá" (bóng đá) and "đa" (tối đa).
    _ambiguous_unaccented = frozenset({"da"})

    @classmethod
    def _is_non_specific(cls, term: str) -> bool:
        words = cls._generic_institutional_words + cls._conversational_words
        if has_diacritics(term):
            return accent_key(term) in {accent_key(word) for word in words}
        if term in cls._ambiguous_unaccented:
            return False
        return term in {strip_accents(word) for word in words}

    @classmethod
    def _yes_no_focus(cls, query: str) -> str:
        """The proposition asked about in Vietnamese ``có ... không``.

        A long subject (e.g. "ký túc xá") must not hide an unsupported
        predicate ("wifi"). Keep accents: "cơ" is not the question marker
        "có", although both may be typed as "co" without diacritics.
        """
        words = cls._raw_words(query)
        starts = set(cls._term_forms("có"))
        ends = set(cls._term_forms("không"))
        for start, word in enumerate(words):
            if cls._query_form(word) in starts:
                for end in range(start + 1, len(words)):
                    if cls._query_form(words[end]) in ends:
                        return " ".join(words[start + 1:end])
                break
        return ""

    @classmethod
    def has_specific_evidence(cls, query: str, hits: list[RankedChunk]) -> bool:
        """Reject coincidental overlap on only university-generic words.

        The clause must state at least half of the specific query words, and
        at least one of them unambiguously (see ``_evidence_support``), so an
        unaccented "giai bong da" is not answered from "học bổng ... tối đa".
        For "có ... không", that same clause must also anchor a specific
        word of the proposition, not just the subject before "có". Do not
        impose another ratio on the predicate: paraphrased verbs such as
        "ảnh hưởng" need not appear verbatim in a clause about graduation.
        """
        groups = []
        for text, minimum in ((query, 0.5), (cls._yes_no_focus(query), 0.0)):
            specific = set(
                cls._query_form(term) for term in accented_content_tokens(text) if not cls._is_non_specific(term)
            )
            if text == query and not specific:
                return False
            if specific:
                groups.append((text, specific, minimum))
        for hit in hits:
            for text, specific, minimum in groups:
                supported, anchored = cls._evidence_support(text, hit.chunk)
                covered = len(specific & supported) / len(specific)
                if covered < minimum or not specific & anchored:
                    break
            else:
                return True
        return False

    @staticmethod
    def _is_valid(chunk: Chunk, ref_date: str | None, include_expired: bool = False) -> bool:
        if include_expired:
            return True
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
