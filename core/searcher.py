"""Dependency-free hybrid retriever for Vietnamese regulation text."""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from datetime import date, datetime
from pathlib import Path

from .models import Chunk, RankedChunk
from .index_storage import atomic_write, index_write_lock
from .index_version import index_fingerprint
from .nlp import accent_key, accented_content_tokens, content_tokens, has_diacritics, normalize, strip_accents
from .retrieval_features import ChunkFeatures, chunk_features
from .question_focus import causal_consequence, causal_focus, facet_supported, question_focus, reward_amount
from .semantic import SemanticEncoder
from .settings import MODELS


INDEX_SCHEMA_VERSION = 2


class StaleIndexError(ValueError):
    """The saved chunks were built with outdated source or extraction rules."""


class HybridSearcher:
    def __init__(self, config):
        self.config = config
        self.chunks: list[Chunk] = []
        self._freqs: list[Counter] = []
        self._lengths: list[int] = []
        self._features: list[ChunkFeatures] = []
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
        # Build/load prepares every document once, even with semantics disabled.
        # Features live on chunks too, so Generator's classmethod calls reuse
        # the same evidence without depending on a particular searcher instance.
        self._features = [self._chunk_features(chunk) for chunk in chunks]
        if not self.config.semantic_enabled:
            self.semantic = None
            self.semantic_error = "Disabled by HV_SEMANTIC"
            return
        self.semantic = SemanticEncoder(self.config.embedding_model, MODELS)
        passages = [self._evidence_text(chunk) for chunk in chunks]
        if not self.semantic.build(passages, index_fingerprint=index_fingerprint(self.config)):
            self.semantic_error = self.semantic.error
        else:
            self.semantic_error = self.semantic.cache_error

    def save(self, path: str, article_version: str | None = None, index_fingerprint: str | None = None) -> None:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps({
            "schema_version": INDEX_SCHEMA_VERSION,
            "article_version": article_version,
            "index_fingerprint": index_fingerprint,
            "chunks": [chunk.to_dict() for chunk in self.chunks],
        }, ensure_ascii=False, indent=2).encode("utf-8")
        with index_write_lock(destination):
            try:
                previous = destination.read_bytes()
            except FileNotFoundError:
                previous = None
            if previous is not None:
                try:
                    data = json.loads(previous)
                    valid = (
                        isinstance(data, dict)
                        and data.get("schema_version", 1) in {1, INDEX_SCHEMA_VERSION}
                        and isinstance(data.get("chunks"), list)
                    )
                    if valid:
                        for chunk in data["chunks"]:
                            Chunk.from_dict(chunk)
                except (ValueError, TypeError, KeyError):
                    valid = False
                # A rebuild after corruption must not destroy a good backup.
                if valid:
                    atomic_write(destination.with_suffix(".json.bak"), previous)
            atomic_write(destination, content)

    @classmethod
    def load(cls, path: str, config, article_version: str | None = None, index_fingerprint: str | None = None):
        """Load a saved index.

        When an expected article version or fingerprint is given, a missing
        or mismatched value raises ``StaleIndexError`` before any embeddings
        are built, so the caller can rebuild instead.
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
        if index_fingerprint is not None and data.get("index_fingerprint") != index_fingerprint:
            raise StaleIndexError("Indexed sources, uploaded documents or chunking settings have changed.")
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
        normalized_query = " ".join(q_tokens)
        try:
            semantic_scores = self.semantic.similarities(query) if self.semantic and self.semantic.available else []
            if semantic_scores:
                self.semantic_error = ""
        except Exception as exc:
            # A runtime model/CPU error must degrade to BM25 instead of
            # dropping the user's request.
            self.semantic_error = f"Semantic query fallback: {type(exc).__name__}: {exc}"
            # Keep the initialized encoder: one transient query failure must
            # not disable semantic search for every subsequent request.
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
            features = self._features[index]
            bm25 += sum(self._idf.get(token, 0.0) * 2.0 for token in q_freq if token in features.heading_forms)
            if len(q_tokens) > 1 and normalized_query in features.normalized_text:
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
    def _chunk_features(cls, chunk: Chunk) -> ChunkFeatures:
        return chunk_features(chunk, cls)

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
        features = cls._chunk_features(chunk)
        return cls._support_from_features(query, features.evidence_words, features.evidence_pairs, features.alias_pairs)

    @classmethod
    def _support_from_features(cls, query, words, pairs, aliases):
        sequence = [cls._query_form(term) for term in accented_content_tokens(query)]
        supported = {form for form in sequence if form in words}
        in_phrase: set[str] = set()
        for left, right in zip(sequence, sequence[1:]):
            if (left, right) in aliases:
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
            for neighbours in (zip(sequence, sequence[1:]), zip(raw_sequence, raw_sequence[1:])):
                in_phrase.update(form for pair in neighbours if pair in pairs for form in pair)
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
        query_forms = cls._query_forms(query)
        if not query_forms:
            return 0.0
        def coverage(item):
            supported = cls._supported_terms(query, item.chunk)
            return sum(form in supported for form in query_forms) / len(query_forms)
        return max(map(coverage, hit), default=0.0) if isinstance(hit, list) else coverage(hit)

    @classmethod
    def phrase_coverage(cls, query: str, hit: RankedChunk) -> float:
        """Measure adjacent query terms for reranking only, never refusal."""
        query_tokens = cls._query_forms(query)
        query_phrases = set(zip(query_tokens, query_tokens[1:]))
        if not query_phrases:
            return 0.0
        return len(query_phrases & cls._chunk_features(hit.chunk).ranking_pairs) / len(query_phrases)

    @classmethod
    def _credit_quantity_topic(cls, query: str) -> str:
        """Identify the topic of a credit-quantity lookup, not eligibility.

        Keep the student's accents for coverage checks. Conversational
        "sinh viên cần" and structural "số ... hệ" are not the requested
        credit category; in particular "cần" must not favour "chuyên cần".
        """
        words = cls._raw_words(query)
        forms = [strip_accents(word) for word in words]
        text = " ".join(forms)
        if "tin chi" not in text or not any(
            marker in text for marker in ("bao nhieu", "may tin chi", "so tin chi")
        ):
            return ""
        fillers = {"sinh", "vien", "can", "so", "he"}
        return " ".join(word for word, form in zip(words, forms) if form not in fillers)

    @classmethod
    def rerank_by_coverage(cls, query: str, hits: list[RankedChunk]) -> list[RankedChunk]:
        """Prefer the evidence that covers most of the student's question.

        BM25 remains the retrieval score; coverage is a transparent second
        stage that fixes a broad document winning over the exact clause.
        For focused questions, put individually supported clauses first:
        the engine's pool-level evidence gate must not let a weaker first
        hit borrow subject/predicate support from a later clause when the
        generator selects its primary passage. Other lookups retain their
        topic/quantity ranking (e.g. generic "điều kiện nhận" wording).
        """
        peak_score = max((hit.score for hit in hits), default=0.0) or 1.0
        peak_bm25 = max((hit.bm25 for hit in hits), default=0.0) or 1.0
        focus = question_focus(query)
        query_terms = set(content_tokens(query))
        asks_for_conditions = {"dieu", "kien"}.issubset(query_terms)
        # "Điều kiện nhận ..." describes the requested kind of rule, not
        # its subject. Matching those words must not outweigh the topic
        # (e.g. scholarship criteria vs foreign-language requirements).
        topic_query = " ".join(
            word for word in cls._raw_words(query)
            if strip_accents(word) not in {"dieu", "kien", "nhan"}
        ) if asks_for_conditions else query
        topic_query = focus.topic if focus.kind or "|" in query else topic_query
        topic_query = topic_query if cls._query_forms(topic_query) else query
        credit_topic = cls._credit_quantity_topic(query)
        credit_terms = set(content_tokens(credit_topic))
        graduation_total = {"tot", "nghiep"}.issubset(credit_terms) and not (
            credit_terms & {"an", "khoa", "luan", "thuc", "tap", "lai"}
        )
        has_focus = bool(cls._question_focus(query)) or bool(focus.kind) or bool(causal_focus(query))
        amounts = [
            reward_amount(cls._chunk_features(hit.chunk).body_ascii) for hit in hits
            if cls.has_specific_evidence(query, [hit])
        ] if focus.kind == "amount" and focus.maximum else []
        units = {amount[0] for amount in amounts if amount}
        reward_sources = {
            hit.chunk.rid for hit in hits
            if focus.kind == "amount" and focus.maximum and cls.has_specific_evidence(query, [hit])
        }
        comparable_amounts = focus.kind == "amount" and focus.maximum and len(units) == 1 and len(reward_sources) == 1

        def rank(hit: RankedChunk) -> float:
            base_rel = (hit.score / peak_score) if hit.score > 0 else (hit.bm25 / peak_bm25)
            coverage = cls.lexical_coverage(topic_query, hit)
            value = (
                (0.40 * coverage)
                + (0.30 * cls.phrase_coverage(topic_query, hit))
                + (0.30 * base_rel)
            )
            if asks_for_conditions:
                evidence = cls._chunk_features(hit.chunk).body_lower
                # "Từ" alone also occurs in funding/payment descriptions,
                # so it does not establish an eligibility condition.
                if any(marker in evidence for marker in ("khi ", "tối thiểu", "không được", "phải", "điều kiện", "được xét", "chỉ xét")):
                    value += 0.18 * coverage
            if credit_topic:
                # A credit question needs an amount in the clause body.
                # Heading/topic overlap alone cannot distinguish attendance,
                # thesis credits, and the full graduation requirement.
                body = cls._chunk_features(hit.chunk).body_ascii
                if re.search(r"\b\d+(?:[.,]\d+)?\s+tin\s+chi\b", body):
                    coverage = cls.lexical_coverage(credit_topic, hit)
                    value += 0.45 * coverage
                    if graduation_total and any(
                        marker in body for marker in ("tich luy du", "chuong trinh dao tao")
                    ):
                        value += 0.30 * coverage
            return value
        return sorted(
            hits,
            key=lambda hit: (
                cls.has_specific_evidence(query, [hit]) if has_focus else True,
                (reward_amount(cls._chunk_features(hit.chunk).body_ascii) or ("", 0))[1] if comparable_amounts else 0,
                rank(hit),
            ),
            reverse=True,
        )

    # Written with diacritics so that, e.g., "dạ" (a polite particle) does not
    # also discard "đá"; unaccented query words compare on stripped forms.
    _generic_institutional_words = (
        "đại", "học", "trường", "sinh", "viên", "quy", "định", "văn", "bản",
        "tổ", "chức", "có", "cơ", "sở", "số", "yêu", "cầu", "bộ", "làm", "vào", "ở",
    )
    _conversational_words = ("em", "mình", "gặp", "xin", "ạ", "dạ")
    _non_specific_accented = frozenset(map(accent_key, _generic_institutional_words + _conversational_words))
    _non_specific_ascii = frozenset(map(strip_accents, _generic_institutional_words + _conversational_words))

    # Unaccented spellings of a non-specific word that are also meaningful
    # words: "da" is "dạ" (particle) but also "đá" (bóng đá) and "đa" (tối đa).
    _ambiguous_unaccented = frozenset({"da"})

    @classmethod
    def _is_non_specific(cls, term: str) -> bool:
        if has_diacritics(term):
            return accent_key(term) in cls._non_specific_accented
        if term in cls._ambiguous_unaccented:
            return False
        return term in cls._non_specific_ascii

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
    def _question_focus(cls, query: str) -> str:
        """Separate a requested feature from its location in descriptive asks.

        In "Wifi ở ký túc xá thế nào?", the location is not evidence about
        wifi. Recognize question structure, never a list of feature topics.
        Match markers with the same accent rules as evidence words.
        """
        yes_no = cls._yes_no_focus(query)
        if yes_no:
            return yes_no
        words = cls._raw_words(query)
        polite = set(form for word in cls._conversational_words for form in cls._term_forms(word))
        while words and cls._query_form(words[-1]) in polite:
            words.pop()
        forms = [cls._query_form(word) for word in words]
        for ending in (("như", "thế", "nào"), ("thế", "nào"), ("ra", "sao"), ("như", "nào")):
            if len(words) <= len(ending):
                continue
            if not all(form in cls._term_forms(marker) for form, marker in zip(forms[-len(ending):], ending)):
                continue
            topic = words[:-len(ending)]
            # These introduce a request for rules/information, rather than
            # naming the requested subject ("Chính sách học phí ...").
            for prefix in (("chính", "sách"), ("quy", "định"), ("thông", "tin")):
                if all(cls._query_form(word) in cls._term_forms(marker) for word, marker in zip(topic, prefix)) and len(topic) > len(prefix):
                    topic = topic[len(prefix):]
                    break
            locations = set(form for word in ("ở", "tại", "trong", "của") for form in cls._term_forms(word))
            for index, word in enumerate(topic):
                if index and cls._query_form(word) in locations:
                    return " ".join(topic[:index])
            return " ".join(topic)
        return ""

    @classmethod
    def has_specific_evidence(cls, query: str, hits: list[RankedChunk]) -> bool:
        """Reject coincidental overlap on only university-generic words.

        The clause must state at least half of the specific query words, and
        at least one of them unambiguously (see ``_evidence_support``), so an
        unaccented "giai bong da" is not answered from "học bổng ... tối đa".
        For "có ... không" and descriptive feature/location questions, that
        same clause must also anchor a specific word of the focus, not just
        the subject or location. Do not
        impose another ratio on the predicate: paraphrased verbs such as
        "ảnh hưởng" need not appear verbatim in a clause about graduation.
        """
        requested = question_focus(query)
        original_query = query
        query = requested.topic or query
        groups = []
        focus = cls._question_focus(query)
        descriptive = bool(focus) and not cls._yes_no_focus(query)
        for text, minimum in ((query, 0.5), (focus, 0.0)):
            ordered_specific = list(dict.fromkeys(
                cls._query_form(term) for term in accented_content_tokens(text) if not cls._is_non_specific(term)
            ))
            specific = set(ordered_specific)
            if text == query and not specific:
                return False
            if specific:
                groups.append((text, specific, minimum, True))
                if text == focus and descriptive:
                    # With an omitted preposition ("Wifi ký túc xá thế
                    # nào"), any later location words must not hide a
                    # missing leading topic. A single requested term need
                    # only be supported here; the full focus still needs
                    # its normal accent/phrase anchor. Keep neighbours for
                    # abbreviation support rather than testing it alone.
                    groups.append((text, {ordered_specific[0]}, 1.0, False))
        for hit in hits:
            body = cls._chunk_features(hit.chunk).body_ascii
            duration_evidence = requested.duration and bool(re.search(r"\bthoi (?:han|gian)\b", body))
            if not facet_supported(requested.kind, body) and not duration_evidence:
                continue
            if requested.kind == "conditions":
                category = re.search(r"\b(?:loại|loai)\s+(\w+)", query)
                if category and cls._query_form(category[1]) not in cls._supported_terms(query, hit.chunk):
                    continue
            if requested.kind in {"timing", "payment_time", "trigger", "actor", "amount", "conditions"}:
                terms = {cls._query_form(term) for term in accented_content_tokens(query)
                         if not cls._is_non_specific(term) and not term.isdigit()}
                if requested.kind == "trigger":
                    # The passive question operator need not be repeated in
                    # "Warning applies when ..."; keep every substantive term.
                    terms.difference_update(cls._term_forms("bị"))
                if requested.duration:
                    # Conjoined aspects may be grounded by complementary
                    # clauses; each clause must still state the whole subject.
                    terms -= {form for word in ("thời", "hạn", "gian") for form in cls._term_forms(word)}
                supported, anchored = cls._evidence_support(query, hit.chunk)
                if requested.kind == "actor":
                    # A procedure's document title may identify *what* is
                    # evaluated. The operation and actor still need body proof.
                    title = cls._chunk_features(hit.chunk).title
                    title_supported, _ = cls._support_from_features(query, title.words, title.pairs, title.aliases)
                    supported |= title_supported
                if not terms or not terms <= supported or not terms & anchored:
                    continue
            # Do not let the predicate hide an unsupported antecedent/event:
            # "forget homework" cannot borrow an unrelated training-score rule.
            prefix = cls._yes_no_subject(original_query)
            if prefix:
                terms = {cls._query_form(term) for term in accented_content_tokens(prefix)
                         if not cls._is_non_specific(term) and not term.isdigit()}
                supported = cls._supported_terms(prefix, hit.chunk)
                if terms and len(terms & supported) / len(terms) < 0.5:
                    continue
            cause = causal_focus(original_query)
            if cause:
                consequence = causal_consequence(original_query)
                effect_terms = {cls._query_form(term) for term in accented_content_tokens(consequence)
                                if not cls._is_non_specific(term) and not term.isdigit()}
                if not effect_terms <= cls._supported_terms(consequence, hit.chunk):
                    continue
                terms = {cls._query_form(term) for term in accented_content_tokens(cause)
                         if not cls._is_non_specific(term) and not term.isdigit()}
                if not terms or not any(
                    len(terms & supported) / len(terms) >= 0.5 and bool(terms & anchored)
                    for fields in cls._chunk_features(hit.chunk).conditions
                    for supported, anchored in [cls._support_from_features(cause, fields.words, fields.pairs, fields.aliases)]
                ):
                    continue
            for text, specific, minimum, require_anchor in groups:
                supported, anchored = cls._evidence_support(text, hit.chunk)
                covered = len(specific & supported) / len(specific)
                if covered < minimum or (require_anchor and not specific & anchored):
                    break
            else:
                return True
        return False

    @classmethod
    def _yes_no_subject(cls, query: str) -> str:
        words = cls._raw_words(query)
        predicate = cls._yes_no_focus(query)
        # Eligibility asks often describe a status in different words from the
        # source ("chưa học xong" vs "đã hoàn thành"). Apply this event guard
        # to consequences/rewards; ordinary eligibility retains its own gates.
        if not re.match(r"^(?:bi\b|duoc (?:cong|thuong)\b)", strip_accents(predicate)):
            return ""
        for index, word in enumerate(words):
            if cls._query_form(word) in cls._term_forms("có"):
                return " ".join(words[:index])
        return ""

    @classmethod
    def has_root_topic(cls, root: str, hit: RankedChunk) -> bool:
        topic = question_focus(root).topic
        specific = [cls._query_form(term) for term in accented_content_tokens(topic) if not cls._is_non_specific(term)]
        return bool(specific) and specific[0] in cls._supported_terms(topic, hit.chunk) and cls.has_specific_evidence(topic, [hit])

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
        except (ValueError, TypeError):
            # Invalid metadata must never make a document appear valid.
            return False
