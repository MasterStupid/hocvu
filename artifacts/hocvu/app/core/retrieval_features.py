"""Immutable, chunk-local lexical features shared by retrieval and generation.

These are runtime attributes, not dataclass fields: Chunk.to_dict() and saved
indexes retain their existing format. No global cache retains old documents.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .models import Chunk
from .nlp import ACADEMIC_TOKEN_ALIASES, accented_content_tokens, content_tokens, strip_accents
from .question_focus import condition_fragments

if TYPE_CHECKING:
    from .searcher import HybridSearcher


@dataclass(frozen=True, slots=True)
class EvidenceFeatures:
    words: frozenset[str]
    pairs: frozenset[tuple[str, str]]
    aliases: frozenset[tuple[str, str]]


def evidence_features(text: str, searcher_type: type[HybridSearcher]) -> EvidenceFeatures:
    tokens = accented_content_tokens(text, expand_aliases=False)
    aliases = set()
    for token in tokens:
        expansion = ACADEMIC_TOKEN_ALIASES.get(strip_accents(token))
        if expansion:
            aliases.update(searcher_type._phrase_index(list(expansion)))
    return EvidenceFeatures(
        frozenset(searcher_type._index_forms(tokens)),
        frozenset(searcher_type._phrase_index(tokens))
        | frozenset(searcher_type._phrase_index(searcher_type._raw_words(text))),
        frozenset(aliases),
    )


@dataclass(frozen=True, slots=True)
class ChunkFeatures:
    source: tuple[type, str, str, str, str]
    heading_forms: frozenset[str]
    normalized_text: str
    evidence_words: frozenset[str]
    evidence_pairs: frozenset[tuple[str, str]]
    alias_pairs: frozenset[tuple[str, str]]
    ranking_pairs: frozenset[tuple[str, str]]
    body_lower: str
    body_ascii: str
    title: EvidenceFeatures
    conditions: tuple[EvidenceFeatures, ...]


def chunk_features(chunk: Chunk, searcher_type: type[HybridSearcher]) -> ChunkFeatures:
    """Precompute once, with lazy support for standalone Generator callers.

    Identity is the actual input, never cid alone. A changed chunk or a helper
    subclass cannot accidentally reuse another document's evidence features.
    Concurrent readers may compute an identical value; publication is one
    assignment of a fully constructed immutable object.
    """
    source = (searcher_type, chunk.version, chunk.reg_title, chunk.art_heading, chunk.text)
    cached = getattr(chunk, "_retrieval_features", None)
    if isinstance(cached, ChunkFeatures) and cached.source == source:
        return cached

    body = searcher_type._clause_body(chunk)
    evidence = searcher_type._evidence_text(chunk)
    tokens = accented_content_tokens(evidence, expand_aliases=False)
    content_pairs = frozenset(searcher_type._phrase_index(tokens))
    alias_pairs = set()
    for token in tokens:
        expansion = ACADEMIC_TOKEN_ALIASES.get(strip_accents(token))
        if expansion:
            alias_pairs.update(searcher_type._phrase_index(list(expansion)))
    # Expanded phrases affect ranking only. Support/anchors must retain the
    # original words and raw stopword adjacency, not expanded abbreviations.
    expanded_tokens = accented_content_tokens(evidence)
    ranking_pairs = (
        content_pairs if expanded_tokens == tokens
        else frozenset(searcher_type._phrase_index(expanded_tokens))
    )
    features = ChunkFeatures(
        source=source,
        heading_forms=frozenset(searcher_type._index_forms(accented_content_tokens(
            f"{chunk.version} {chunk.reg_title} {chunk.art_heading}",
        ))),
        normalized_text=" ".join(content_tokens(chunk.text)),
        evidence_words=frozenset(searcher_type._index_forms(tokens)),
        evidence_pairs=content_pairs | frozenset(searcher_type._phrase_index(searcher_type._raw_words(evidence))),
        alias_pairs=frozenset(alias_pairs),
        ranking_pairs=ranking_pairs,
        body_lower=body.lower(),
        body_ascii=strip_accents(body).lower(),
        title=evidence_features(f"{chunk.reg_title} {chunk.version}", searcher_type),
        conditions=tuple(evidence_features(part, searcher_type) for part in condition_fragments(body)),
    )
    setattr(chunk, "_retrieval_features", features)
    return features
