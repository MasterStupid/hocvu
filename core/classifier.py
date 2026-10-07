"""Intent routing and scope protection for HocVu AI."""
from __future__ import annotations

from enum import Enum
import re

from .nlp import normalize, strip_accents


class Intent(str, Enum):
    GREETING = "greeting"
    ACADEMIC_RULES = "academic_rules"
    OUT_OF_SCOPE = "out_of_scope"
    TOXIC = "unsafe"


class Classifier:
    """Small, transparent classifier appropriate for an offline pilot."""

    _greetings = ("xin chao", "chao ban", "hello", "hi", "cam on")
    _toxic = ("giết", "giet", "tu sat", "tự sát", "danh bom")

    def classify(self, question: str) -> Intent:
        q = strip_accents(normalize(question)).lower()
        def has_phrase(phrase: str) -> bool:
            return bool(re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", q))

        if any(has_phrase(word) for word in self._toxic):
            return Intent.TOXIC
        # Phrase boundaries matter: the greeting "hi" must not turn "thi
        # lại" (a core academic query) into a greeting.
        if len(q.split()) <= 5 and any(has_phrase(word) for word in self._greetings):
            return Intent.GREETING
        # Do not reject legitimate policy topics by a closed vocabulary. The
        # retriever's evidence threshold is the scope gate: unsupported
        # questions still receive a grounded refusal, while new subjects such
        # as "song ngành" or "IELTS" can reach their source documents.
        return Intent.ACADEMIC_RULES
