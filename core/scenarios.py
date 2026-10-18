"""Small, transparent query understanding rules for common student scenarios."""
from __future__ import annotations

import re

from .nlp import expand_academic_terms, normalize, strip_accents


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
    prefixes = (
        "con dieu kien", "con truong hop", "the con", "noi ro hon", "cu the hon",
        "con gi", "vay con", "vay neu", "neu vay", "neu the", "vay thi", "the thi",
        "the con", "the thi", "con nua khong", "dieu do",
    )
    if any(q.startswith(prefix) for prefix in prefixes):
        return True
    words = q.split()
    if len(words) <= 4 and any(w in words for w in ("do", "nay", "ay", "kia", "sao", "khong")):
        return True
    return False


def is_historical_query(question: str) -> bool:
    """Whether the user explicitly asks to inspect a superseded regulation."""
    q = strip_accents(normalize(question)).lower()
    return any(phrase in q for phrase in ("quy dinh cu", "ban cu", "phien ban cu", "nam 2024", "2024"))


def is_comparison_query(question: str) -> bool:
    q = strip_accents(normalize(question)).lower()
    years = re.findall(r"\b20\d{2}\b", q)
    return len(set(years)) >= 2 or any(phrase in q for phrase in (
        "so sanh", "khac gi", "khac nhau", "doi chieu",
        "giua cac phien ban", "giua hai phien ban", "qua cac phien ban",
    ))


def comparison_topic(question: str) -> str:
    """Remove version-comparison framing, not the subject or its predicates.

    Keep accents for the ordinary evidence gates. In particular an unsupported
    feature such as wifi must not be hidden by a supported location.
    """
    words = re.findall(r"\w+", normalize(question))
    forms = [strip_accents(word).lower() for word in words]
    for scope in ("giua cac phien ban", "giua hai phien ban", "qua cac phien ban"):
        marker = scope.split()
        for index in range(len(words) - len(marker) + 1):
            if forms[index:index + len(marker)] != marker:
                continue
            tail = forms[index + len(marker):]
            # Only strip comparison framing. Any additional requested feature
            # must remain in the original query and pass the normal gate.
            if any(word not in {"quy", "dinh", "khong", "nhu", "the", "nao", "a", "cu", "moi"} for word in tail):
                return question
            topic = words[:index]
            topic_forms = forms[:index]
            for ending in ("co thay doi", "thay doi", "co khac nhau", "khac nhau", "co khac", "khac"):
                suffix = ending.split()
                if topic_forms[-len(suffix):] == suffix:
                    topic = topic[:-len(suffix)]
                    break
            # Retain descriptive focus semantics: "wifi ký túc xá" must still
            # require evidence for wifi rather than passing on the location.
            return " ".join(topic) + " như thế nào"
    return question


def expand_retrieval_query(question: str) -> str:
    """Add concepts implied by a student scenario, without altering its meaning."""
    expanded = expand_academic_terms(question)
    if is_attendance_training_scenario(expanded):
        return f"{expanded} vắng mặt điểm danh chuyên cần ý thức học tập điểm rèn luyện"
    return expanded
