import re
import unicodedata
import hashlib
from typing import List, Set

VI_STOPWORDS: Set[str] = {
    "là", "và", "của", "các", "có", "được", "cho", "trong", "để", "với", "một", "những", 
    "này", "khi", "tại", "sẽ", "đó", "không", "về", "như", "theo", "người", "trên", 
    "từ", "nếu", "đã", "thì", "đến", "hoặc", "cũng", "do", "hay", "sự", "chỉ", "ra", 
    "phải", "đang", "nên", "nào", "bởi", "lại", "mà", "còn", "cùng", "qua", "nơi", 
    "nhưng", "việc", "sau", "mọi"
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

def tokenize(text: str) -> List[str]:
    text = normalize(text)
    text = strip_accents(text).lower()
    tokens = re.findall(r'\w+', text)
    return tokens

def content_tokens(text: str) -> List[str]:
    tokens = tokenize(text)
    return [t for t in tokens if t not in VI_STOPWORDS]

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
