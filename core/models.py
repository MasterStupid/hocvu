"""Mô hình dữ liệu HocVu AI — dataclass thuần, JSON-serializable.

Thiết kế dùng tên trường ngắn gọn, nhất quán và tách rõ tầng:
Source → Index → Retrieval → Response.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


# ═══════════════════════════════════════════════════════════════════════════
# TẦNG NGUỒN (source layer — cấu trúc văn bản gốc)
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class Clause:
    """Một khoản trong điều."""
    cid: str           # vd "1", "2a"
    content: str       # nội dung khoản

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Article:
    """Một điều trong văn bản."""
    aid: str           # vd "Điều 1"
    heading: str       # tên điều
    clauses: list[Clause] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        parts = [f"{self.aid}. {self.heading}"]
        for c in self.clauses:
            parts.append(f"Khoản {c.cid}. {c.content}")
        return " ".join(parts)

    def to_dict(self) -> dict:
        return {"aid": self.aid, "heading": self.heading,
                "clauses": [c.to_dict() for c in self.clauses]}


@dataclass
class Regulation:
    """Một văn bản quy chế / quy định."""
    rid: str
    title: str
    category: str      # loại văn bản
    version: str
    valid_from: str     # YYYY-MM-DD
    valid_until: str | None
    issuer: str
    articles: list[Article] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "rid": self.rid, "title": self.title, "category": self.category,
            "version": self.version, "valid_from": self.valid_from,
            "valid_until": self.valid_until, "issuer": self.issuer,
            "articles": [a.to_dict() for a in self.articles],
        }

    @classmethod
    def from_dict(cls, d: dict) -> Regulation:
        return cls(
            rid=d["rid"], title=d["title"], category=d.get("category", ""),
            version=d.get("version", ""), valid_from=d.get("valid_from", ""),
            valid_until=d.get("valid_until"), issuer=d.get("issuer", ""),
            articles=[
                Article(
                    aid=a["aid"], heading=a.get("heading", ""),
                    clauses=[Clause(c["cid"], c["content"]) for c in a.get("clauses", [])],
                )
                for a in d.get("articles", [])
            ],
        )


# ═══════════════════════════════════════════════════════════════════════════
# TẦNG CHỈ MỤC (index layer — chunk đã chia)
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class Chunk:
    """Đơn vị truy xuất nhỏ nhất."""
    cid: str            # chunk_id duy nhất
    rid: str
    reg_title: str
    version: str
    valid_from: str
    valid_until: str | None
    aid: str            # article id
    art_heading: str    # article heading
    clause_ids: list[str]
    text: str
    seq: int = 0        # thứ tự trong article

    @property
    def cite_label(self) -> str:
        lbl = self.aid
        if self.clause_ids:
            lbl += f", K.{','.join(self.clause_ids)}"
        return lbl

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Chunk:
        return cls(**d)


# ═══════════════════════════════════════════════════════════════════════════
# TẦNG TRUY XUẤT (retrieval layer)
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class RankedChunk:
    """Chunk đã được chấm điểm."""
    chunk: Chunk
    score: float
    bm25: float = 0.0
    vec: float = 0.0

    def to_dict(self, include_retrieved: bool = False) -> dict:
        result = {
            "chunk": self.chunk.to_dict(),
            "score": round(self.score, 5),
            "bm25": round(self.bm25, 5),
            "vec": round(self.vec, 5),
            "cite": self.chunk.cite_label,
        }


@dataclass
class Reference:
    """Trích dẫn kèm câu trả lời."""
    rid: str
    reg_title: str
    aid: str
    art_heading: str
    clause_ids: list[str]
    excerpt: str

    def to_dict(self) -> dict:
        return asdict(self)


# ═══════════════════════════════════════════════════════════════════════════
# TẦNG HỘI THOẠI (conversation layer)
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class SpeechResult:
    """Kết quả nhận dạng giọng nói."""
    text: str
    confidence: float
    lang: str = "vi"
    provider: str = "local"
    duration: float | None = None
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Response:
    """Phản hồi hoàn chỉnh cho một câu hỏi."""
    query: str
    answer: str
    references: list[Reference] = field(default_factory=list)
    confidence: float = 0.0
    refused: bool = False
    refusal_reason: str = ""
    intent: str = "other"
    speech: SpeechResult | None = None
    retrieved: list[RankedChunk] = field(default_factory=list)
    audio_url: str | None = None
    providers: dict[str, str] = field(default_factory=dict)
    timing: dict[str, float] = field(default_factory=dict)
    session_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    card: dict[str, Any] = field(default_factory=dict)

    def to_dict(self, include_retrieved: bool = False) -> dict:
        result = {
            "query": self.query,
            "answer": self.answer,
            "references": [r.to_dict() for r in self.references],
            "confidence": round(self.confidence, 4),
            "refused": self.refused,
            "refusal_reason": self.refusal_reason,
            "intent": self.intent,
            "speech": self.speech.to_dict() if self.speech else None,
            "audio_url": self.audio_url,
            "providers": self.providers,
            "timing": {k: round(v, 2) for k, v in self.timing.items()},
            "session_id": self.session_id,
            "metadata": self.metadata,
            "card": self.card,
        }
        if include_retrieved:
            result["retrieved"] = [r.to_dict() for r in self.retrieved]
        return result


# ═══════════════════════════════════════════════════════════════════════════
# TẦNG KIỂM THỬ
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class TestQuestion:
    """Một câu hỏi kiểm thử có đáp án vàng."""
    qid: str
    question: str
    expected: str           # đáp án vàng
    source_aids: list[str]  # Điều nguồn
    source_rids: list[str]  # Văn bản nguồn
    category: str           # factual | conditional | comparison | out_of_scope
    difficulty: str         # easy | medium | hard
    should_refuse: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> TestQuestion:
        return cls(**d)
