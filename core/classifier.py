"""Intent routing and scope protection for HocVu AI."""
from __future__ import annotations

from enum import Enum

from .nlp import normalize, strip_accents


class Intent(str, Enum):
    GREETING = "greeting"
    ACADEMIC_RULES = "academic_rules"
    OUT_OF_SCOPE = "out_of_scope"
    TOXIC = "unsafe"


class Classifier:
    """Small, transparent classifier appropriate for an offline pilot."""

    _greetings = ("xin chao", "chao ban", "hello", "hi", "cam on")
    _academic = (
        "quy che", "hoc vu", "tin chi", "hoc phan", "dang ky", "huy hoc",
        "bao luu", "tot nghiep", "diem", "canh bao", "ky luat", "khen thuong",
        "thuc tap", "do an", "hoc lai", "hoc bong", "nghi hoc",
        "tai lieu", "de tai", "muc tieu", "phuong phap", "kien truc", "rag",
        "stt", "tts", "bao cao", "chuong", "noi dung", "ket qua", "he thong",
        "truy xuat", "chi so", "thu nghiem", "ket luan", "phan mem",
        "thong bao", "thoi han", "cung cap", "thong tin", "cccd", "hemis",
        "quyet dinh", "dieu khoan", "van ban", "bieu mau", "huong dan",
    )
    _toxic = ("giết", "giet", "tu sat", "tự sát", "danh bom")

    def classify(self, question: str) -> Intent:
        q = strip_accents(normalize(question)).lower()
        if any(word in q for word in self._toxic):
            return Intent.TOXIC
        if len(q.split()) <= 5 and any(word in q for word in self._greetings):
            return Intent.GREETING
        return Intent.ACADEMIC_RULES if any(word in q for word in self._academic) else Intent.OUT_OF_SCOPE
