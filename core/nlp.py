import re
import unicodedata
import hashlib
from typing import List, Set

VI_STOPWORDS: Set[str] = {
    "là", "và", "của", "các", "có", "được", "cho", "trong", "để", "với", "một", "những", 
    "này", "khi", "tại", "sẽ", "đó", "không", "về", "như", "theo", "người", "trên", 
    "từ", "nếu", "đã", "thì", "đến", "hoặc", "cũng", "do", "hay", "sự", "chỉ", "ra", 
    "phải", "đang", "nên", "nào", "bởi", "mà", "còn", "cùng", "qua", "nơi",
    "nhưng", "việc", "sau", "mọi", "bao", "nhiêu", "mấy", "gì", "sao",
    "thế", "thế nào", "như nào", "của tôi", "tôi", "bạn", "vậy", "quy",
    "định", "bản", "phiên", "cũ", "mới", "phép", "khác"
}

def normalize(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def strip_accents(text: str) -> str:
    text = unicodedata.normalize('NFD', text)
    text = re.sub(r'[\u0300-\u036f]', '', text)
    text = re.sub(r'[đĐ]', 'd', text)
    return text


# ``tokenize`` removes Vietnamese diacritics, so stopwords must be normalized
# the same way. Keeping the human-readable source list above avoids a fragile,
# hand-maintained second list of unaccented words.
# A few unaccented spellings collide with meaningful academic words after
# accent stripping (``thì``/``thi``, ``tôi``/``tối``, ``đã``/``đa``). They
# must never be removed from a no-accent student query.
_AMBIGUOUS_ASCII_STOPWORDS = {"thi", "toi", "da"}
NORMALIZED_VI_STOPWORDS: Set[str] = {
    strip_accents(word).lower() for word in VI_STOPWORDS
    if strip_accents(word).lower() not in _AMBIGUOUS_ASCII_STOPWORDS
}
ACADEMIC_TOKEN_ALIASES = {
    "drl": ("diem", "ren", "luyen"),
    "rl": ("diem", "ren", "luyen"),
    "hbkkht": ("hoc", "bong", "khuyen", "khich", "hoc", "tap"),
}


def expand_academic_terms(text: str) -> str:
    """Normalize common student shorthand to terms present in regulations.

    This is deterministic query normalization, not answer generation: it only
    replaces a student's wording with an equivalent retrieval term.
    """
    normalized = normalize(text)
    replacements = (
        (r"\bđrl\b|\brl\b", "điểm rèn luyện"),
        (r"\bnghỉ học\b|\bnghỉ\b", "vắng mặt"),
        (r"%", " phần trăm "),
        (r"\bhọc 2 ngành\b|\bhai ngành\b", "học song ngành"),
        (r"\bhọc phí\b", "học phí tài chính"),
        (r"\bquy đổi\b", "quy đổi chứng chỉ"),
        (r"\bđược tính như thế nào\b|\btính như thế nào\b", "đánh giá dựa trên tỷ trọng"),
    )
    for pattern, replacement in replacements:
        normalized = re.sub(pattern, replacement, normalized, flags=re.IGNORECASE)
    if re.search(r"\bsong ngành\b", normalized, flags=re.IGNORECASE):
        normalized = f"{normalized} học cùng lúc hai chương trình"
    return normalize(normalized)

def tokenize(text: str) -> List[str]:
    text = normalize(text)
    text = strip_accents(text).lower()
    tokens = re.findall(r'\w+', text)
    return tokens

def content_tokens(text: str) -> List[str]:
    # Decide whether a token is a stopword while its accents are intact, then
    # strip accents for retrieval. This preserves "tối đa" and "thi lại"
    # while still making "là", "bao", "nhiêu" harmless.
    raw_tokens = re.findall(r"\w+", normalize(text).lower())
    result = []
    for token in raw_tokens:
        if token in VI_STOPWORDS or (token.isascii() and token in NORMALIZED_VI_STOPWORDS):
            continue
        normalized_token = strip_accents(token)
        result.extend(ACADEMIC_TOKEN_ALIASES.get(normalized_token, (normalized_token,)))
    return result

def ngrams(tokens: List[str], n: int) -> List[str]:
    if n <= 0:
        return []
    return [" ".join(tokens[i:i+n]) for i in range(len(tokens)-n+1)]

def sentences(text: str) -> List[str]:
    text = normalize(text)
    sents = re.split(r'(?<=[.!?])\s+', text)
    return [s for s in sents if s]

def has_number(text: str) -> bool:
    return bool(re.search(r'\d', text))

def stable_hash(text: str) -> int:
    h = hashlib.blake2b(text.encode('utf-8'), digest_size=8)
    return int.from_bytes(h.digest(), byteorder='big')

def jaccard(set_a: Set, set_b: Set) -> float:
    if not set_a and not set_b:
        return 1.0
    intersection = len(set_a.intersection(set_b))
    union = len(set_a.union(set_b))
    return intersection / union if union > 0 else 0.0

def truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len-3] + "..."
