"""Cấu hình hệ thống HocVu AI — type-safe, env-driven.

Mọi tham số đều có giá trị mặc định offline. Override bằng biến môi trường
hoặc file .env. Không cần bất kỳ thư viện bên thứ ba nào.
"""

from __future__ import annotations

import os
import math
from dataclasses import dataclass, field
from pathlib import Path


# ── Đường dẫn ────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[1]
# Keep runtime state outside the source tree when the app is deployed.  Local
# development keeps the original ``./data`` layout; a hosted service can set
# HV_DATA_DIR to its persistent-volume mount (for example ``/var/data``).
DATA = Path(os.environ.get("HV_DATA_DIR", str(ROOT / "data"))).expanduser().resolve()
RAW  = DATA / "raw"
IDX  = DATA / "index"
AUD  = DATA / "audio"
DOCS = DATA / "documents"
MODELS = DATA / "models"
UI   = ROOT / "ui"

CORPUS_JSON = RAW / "corpus.json"
CORPUS_MD   = RAW / "corpus.md"
QA_JSON     = RAW / "qa_testset.json"
INDEX_JSON  = IDX / "index.json"
SESSION_DB  = DATA / "sessions.db"
SERVER_META = DATA / "server.json"
EVAL_JSON   = DATA / "eval_result.json"
EVAL_CSV    = DATA / "eval_result.csv"


def _e(name: str, fallback: str) -> str:
    v = os.environ.get(name)
    return fallback if v is None or v == "" else v


def _i(name: str, fallback: int) -> int:
    try:
        return int(_e(name, str(fallback)))
    except ValueError as exc:
        raise ValueError(f"{name} phải là số nguyên hợp lệ.") from exc


def _f(name: str, fallback: float) -> float:
    try:
        value = float(_e(name, str(fallback)))
    except ValueError as exc:
        raise ValueError(f"{name} phải là số thực hợp lệ.") from exc
    if not math.isfinite(value):
        raise ValueError(f"{name} phải là số hữu hạn.")
    return value


def _b(name: str, fallback: bool) -> bool:
    value = _e(name, str(fallback)).strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} phải là true/false (hoặc 1/0).")


@dataclass(frozen=False)
class AppConfig:
    """Tham số toàn hệ thống — ghi đè bằng env var khi cần."""

    # ── Retrieval ───────────────────────────────
    top_k: int = 5
    bm25_pool: int = 15          # BM25 recall pool
    vec_pool: int = 15           # vector recall pool
    bm25_weight: float = 0.10   # lexical tie-breaker; semantic retrieval leads
    embed_dim: int = 1024
    embedding_model: str = "intfloat/multilingual-e5-small"
    semantic_enabled: bool = True

    # ── Chunking ────────────────────────────────
    max_chunk_chars: int = 800
    overlap_sents: int = 1

    # ── Generation ──────────────────────────────
    confidence_floor: float = 0.28
    semantic_floor: float = 0.20
    lexical_coverage_floor: float = 0.50
    max_units: int = 2

    # ── Session / Dialogue ──────────────────────
    max_history: int = 8

    # ── Backends ────────────────────────────────
    llm_backend: str = "local"     # local | openai
    stt_backend: str = "local"     # local | whisper
    tts_backend: str = "local"     # local | edge

    # ── OpenAI (chỉ khi llm_backend=openai) ────
    openai_key: str = ""
    openai_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    openai_embed: str = "text-embedding-3-small"

    # ── Whisper / TTS ───────────────────────────
    whisper_size: str = "small"
    tts_voice: str = "vi-VN-HoaiMyNeural"
    api_token: str = ""
    rate_limit_per_minute: int = 120

    # ── Misc ────────────────────────────────────
    seed: int = 20262027

    extra: dict = field(default_factory=dict)

    # ── Helpers ─────────────────────────────────
    def summary(self) -> dict:
        """Tóm tắt config (an toàn, không lộ key)."""
        return {
            "top_k": self.top_k,
            "bm25_weight": self.bm25_weight,
            "embed_dim": self.embed_dim,
            "embedding_model": self.embedding_model,
            "semantic_enabled": self.semantic_enabled,
            "confidence_floor": self.confidence_floor,
            "semantic_floor": self.semantic_floor,
            "lexical_coverage_floor": self.lexical_coverage_floor,
            "llm": self.llm_backend,
            "stt": self.stt_backend,
            "tts": self.tts_backend,
            "rate_limit_per_minute": self.rate_limit_per_minute,
        }


def load_config() -> AppConfig:
    """Nạp cấu hình từ env → fallback mặc định."""
    config = AppConfig(
        top_k=_i("HV_TOP_K", 5),
        bm25_pool=_i("HV_BM25_POOL", 15),
        vec_pool=_i("HV_VEC_POOL", 15),
        bm25_weight=_f("HV_BM25_WEIGHT", 0.10),
        embed_dim=_i("HV_EMBED_DIM", 1024),
        embedding_model=_e("HV_EMBEDDING_MODEL", "intfloat/multilingual-e5-small"),
        semantic_enabled=_b("HV_SEMANTIC", True),
        max_chunk_chars=_i("HV_MAX_CHUNK_CHARS", 800),
        overlap_sents=_i("HV_OVERLAP_SENTS", 1),
        confidence_floor=_f("HV_CONFIDENCE_FLOOR", 0.28),
        semantic_floor=_f("HV_SEMANTIC_FLOOR", 0.20),
        lexical_coverage_floor=_f("HV_LEXICAL_COVERAGE_FLOOR", 0.50),
        max_units=_i("HV_MAX_UNITS", 2),
        max_history=_i("HV_MAX_HISTORY", 8),
        llm_backend=_e("HV_LLM", "local").lower(),
        stt_backend=_e("HV_STT", "local").lower(),
        tts_backend=_e("HV_TTS", "local").lower(),
        openai_key=_e("OPENAI_API_KEY", ""),
        openai_url=_e("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        openai_model=_e("OPENAI_MODEL", "gpt-4o-mini"),
        openai_embed=_e("OPENAI_EMBED_MODEL", "text-embedding-3-small"),
        whisper_size=_e("WHISPER_MODEL", "small"),
        tts_voice=_e("TTS_VOICE", "vi-VN-HoaiMyNeural"),
        api_token=_e("HV_API_TOKEN", ""),
        rate_limit_per_minute=_i("HV_RATE_LIMIT_PER_MINUTE", 120),
        seed=_i("HV_SEED", 20262027),
    )
    for name in ("top_k", "bm25_pool", "vec_pool", "embed_dim", "max_chunk_chars", "max_units", "max_history", "rate_limit_per_minute"):
        if getattr(config, name) <= 0:
            raise ValueError(f"{name} phải lớn hơn 0.")
    for name in ("bm25_weight", "confidence_floor", "semantic_floor", "lexical_coverage_floor"):
        if not 0 <= getattr(config, name) <= 1:
            raise ValueError(f"{name} phải nằm trong khoảng 0 đến 1.")
    return config


def ensure_dirs() -> None:
    """Tạo sẵn thư mục cần thiết."""
    for d in (DATA, RAW, IDX, AUD, DOCS, MODELS):
        d.mkdir(parents=True, exist_ok=True)
