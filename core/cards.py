"""Structured presentation data for grounded answer cards.

This module only packages evidence already selected by the retrieval pipeline;
it never creates a new institutional claim.
"""
from __future__ import annotations

import re
from collections import defaultdict

from .corpus import build_corpus, build_qa
from .models import Reference, RankedChunk
from .nlp import content_tokens


TOPIC_LABELS = {
    "factual": "Quy định học vụ",
    "conditional": "Điều kiện áp dụng",
    "comparison": "So sánh quy định",
}


def build_suggestion_topics(seed: int) -> list[dict]:
    """Return only in-scope, answerable questions from the bundled QA set."""
    grouped: dict[str, list[str]] = defaultdict(list)
    for item in build_qa(build_corpus(seed=seed), seed=seed):
        if not item.should_refuse:
            grouped[item.category].append(item.question)
    return [
        {"topic": TOPIC_LABELS.get(category, category), "questions": sorted(set(questions))[:6]}
        for category, questions in sorted(grouped.items())
        if questions
    ]


def best_suggestions(question: str, topics: list[dict], limit: int = 3) -> list[str]:
    query_terms = set(content_tokens(question))
    question_key = " ".join(content_tokens(question))
    candidates = [
        candidate for topic in topics for candidate in topic["questions"]
        if " ".join(content_tokens(candidate)) != question_key
    ]
    scored = sorted(
        candidates,
        key=lambda candidate: (-len(query_terms.intersection(content_tokens(candidate))), candidate),
    )
    return scored[:limit]


def _source_chunks(references: list[Reference], hits: list[RankedChunk]):
    chunks = []
    for reference in references:
        match = next(
            (hit.chunk for hit in hits if hit.chunk.rid == reference.rid and hit.chunk.aid == reference.aid),
            None,
        )
        chunks.append(match)
    return chunks


def _display_date(value: str) -> str:
    parts = value.split("-")
    return "/".join(reversed(parts)) if len(parts) == 3 else value


def build_notes(references: list[Reference], hits: list[RankedChunk]) -> list[dict]:
    """Extract compact, source-derived context for the answer card."""
    notes: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for chunk in _source_chunks(references, hits):
        if not chunk:
            continue
        if chunk.valid_from and ("effective", chunk.valid_from) not in seen:
            notes.append({"icon": "calendar", "text": f"Hiệu lực từ {_display_date(chunk.valid_from)}"})
            seen.add(("effective", chunk.valid_from))
        if chunk.version and ("version", chunk.version) not in seen:
            notes.append({"icon": "document", "text": f"Phiên bản: {chunk.version}"})
            seen.add(("version", chunk.version))
        for sentence in re.split(r"(?<=[.!?])\s+", chunk.text):
            if "áp dụng cho" in sentence.lower():
                key = ("scope", sentence)
                if key not in seen:
                    notes.append({"icon": "scope", "text": sentence.strip()})
                    seen.add(key)
                break
        for sentence in re.split(r"(?<=[.!?])\s+", chunk.text):
            if "thay thế" in sentence.lower():
                key = ("replacement", sentence)
                if key not in seen:
                    notes.append({"icon": "replace", "text": sentence.strip()})
                    seen.add(key)
                break
    return notes[:5]


def build_grounding(references: list[Reference], normalized_score: float) -> dict:
    source_count = len(references)
    level = 0 if not source_count else 2 if source_count == 1 else 3 if source_count == 2 else 4
    if source_count and normalized_score > 0.7:
        level = min(5, level + 1)
    label = "mạnh" if level >= 4 else "trung bình" if level == 3 else "yếu"
    return {"level": level, "label": label, "source_count": source_count}


def build_card(answer: str, references: list[Reference], hits: list[RankedChunk], normalized_score: float, suggestions: list[str] | None = None) -> dict:
    paragraphs = [paragraph.strip() for paragraph in answer.split("\n\n") if paragraph.strip()]
    # Stage 1 mapping: generator output preserves selected chunk order. For
    # explanatory scenario paragraphs, the same deterministic order remains
    # preferable to an ungrounded semantic guess.
    verdict_segments = [
        {"text": paragraph, "cites": [min(index + 1, len(references))] if references else []}
        for index, paragraph in enumerate(paragraphs)
    ]
    return {
        "verdict_segments": verdict_segments,
        "grounding": build_grounding(references, normalized_score),
        "notes": build_notes(references, hits),
        "suggestions": suggestions or [],
    }
