"""Small, transparent query understanding rules for common student scenarios."""
from __future__ import annotations

import re

from .nlp import normalize, strip_accents


def is_attendance_training_scenario(question: str) -> bool:
    q = strip_accents(normalize(question)).lower()
    def has_phrase(phrase: str) -> bool:
        return bool(re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", q))
    mentions_absence = any(has_phrase(term) for term in ("nghi", "vang mat", "bo hoc"))
    mentions_class_time = any(has_phrase(term) for term in ("tiet", "buoi hoc", "di hoc"))
    mentions_training = has_phrase("ren luyen") or has_phrase("drl")
    return mentions_absence and mentions_class_time and mentions_training


def is_contextual_follow_up(question: str) -> bool:
    """Recognise short references to the immediately preceding topic only."""
    q = strip_accents(normalize(question)).lower()
    return any(q.startswith(prefix) for prefix in (
        "con dieu kien", "con truong hop", "the con", "noi ro hon", "cu the hon",
    ))


def expand_retrieval_query(question: str) -> str:
    """Add concepts implied by a student scenario, without altering its meaning."""
    if is_attendance_training_scenario(question):
        return f"{question} vắng mặt điểm danh chuyên cần ý thức học tập điểm rèn luyện"
    return question
