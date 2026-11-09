"""Conservative question framing and source-facet checks, not answer templates.

Only request operators are removed. Unknown subjects and requested features stay
in the topic and must be supported; source titles are not ordinary policy proof.
"""
from dataclasses import dataclass
from decimal import Decimal
import re

from .nlp import accent_key, has_diacritics, normalize, strip_accents


def without_phrases(text: str, phrases: tuple[str, ...]) -> str:
    words = re.findall(r"\w+", normalize(text).lower())
    for phrase in phrases:
        marker = phrase.split()
        index = 0
        while index <= len(words) - len(marker):
            if all(
                accent_key(word) == accent_key(expected) if has_diacritics(word)
                else strip_accents(word) == strip_accents(expected)
                for word, expected in zip(words[index:index + len(marker)], marker)
            ):
                del words[index:index + len(marker)]
            else:
                index += 1
    return " ".join(words)


@dataclass(frozen=True, slots=True)
class QuestionFocus:
    topic: str
    kind: str = ""
    maximum: bool = False
    duration: bool = False


def question_focus(question: str) -> QuestionFocus:
    q = strip_accents(normalize(question)).lower()
    if "|" in question:
        # Keep resolved antecedents and all substantive follow-up features.
        return QuestionFocus(without_phrases(question, (
            "còn điều kiện nào khác không", "còn điều kiện nào khác",
            "còn điều kiện", "còn cái đó", "điều kiện", "là gì",
        )))
    if "hieu luc" in q and re.search(r"\b(?:tu khi nao|tu ngay nao|khi nao|tu bao gio)\b", q):
        return QuestionFocus(without_phrases(question, (
            "có hiệu lực từ khi nào", "có hiệu lực từ ngày nào",
            "hiệu lực từ khi nào", "hiệu lực từ ngày nào", "có hiệu lực khi nào",
            "hiệu lực khi nào", "có hiệu lực từ bao giờ",
        )), "metadata_start")
    identity_question = bool(re.search(r"\b(?:ban nao|van ban nao|quy dinh\b.*\bnao)\b", q))
    if identity_question and (
        "hien hanh" in q or ("hieu luc" in q and ("hien tai" in q or "dang" in q))
    ):
        return QuestionFocus(without_phrases(question, (
            "đang có hiệu lực hiện tại", "đang có hiệu lực", "có hiệu lực hiện tại",
            "hiện hành", "là bản nào", "là văn bản nào", "nào", "hiện tại",
        )), "metadata_current")
    if re.search(r"\b(?:thoi gian nao|khi nao|luc nao|bao gio|bao lau)\b", q):
        topic = without_phrases(question, (
            "vào thời gian nào", "thời gian nào", "khi nào", "lúc nào",
            "bao giờ", "bao lâu", "được phát", "được chi trả", "chi trả",
            "thời gian", "thì được", "được", "là",
        ))
        topic = re.sub(r"^(?:muốn|muon)\s+", "", topic)
        kind = "timing"
        # "When is a student warned?" asks for a trigger, not a calendar.
        # Explicit duration questions ("bị ... bao lâu") remain temporal.
        if (
            re.search(r"\b(?:khi nao|luc nao|bao gio)\b", q)
            and not re.search(r"\b(?:bao lau|thoi gian nao)\b", q)
            and re.search(r"\b(?:bị|bi)\b", normalize(question).lower())
        ):
            kind = "trigger"
        if re.search(r"\b(?:phat|chi tra|chuyen khoan)\b", q):
            kind = "payment_time"
        return QuestionFocus(topic, kind)
    if re.match(r"^(?:ai|nguoi nao|don vi nao)\b", q):
        topic = without_phrases(question, ("ai là người", "người nào", "đơn vị nào", "ai", "là"))
        # The ordinary Vietnamese operation, not a corpus-specific answer.
        topic = re.sub(r"\bchấm điểm\b", "đánh giá", topic)
        topic = re.sub(r"\bcham diem\b", "danh gia", topic)
        return QuestionFocus(topic, "actor")
    if "tien thuong" in q or re.search(r"\b(?:thuong|nhan) bao nhieu tien\b", q):
        maximum = "nhat" in q or "cao nhat" in q or "toi da" in q
        phrases = ("tiền", "cho sinh viên", "sinh viên", "là bao nhiêu", "bao nhiêu", "cao nhất", "nhất")
        # Colloquial "học giỏi nhất" is a superlative, not the named "loại Giỏi".
        if maximum and "loai" not in q:
            phrases = ("học giỏi",) + phrases
        return QuestionFocus(without_phrases(question, phrases), "amount", maximum)
    if "dieu kien" in q:
        topic = without_phrases(question, (
            "muốn được", "muốn nhận", "để được", "điều kiện để nhận",
            "điều kiện nhận", "cần những điều kiện", "cần điều kiện",
            "cần những", "những điều kiện", "đủ điều kiện", "điều kiện", "là gì",
        ))
        words = topic.split()
        if words and words[0] in {"muốn", "muon"}:
            words.pop(0)
        if words and words[-1] in {"gì", "gi"}:
            words.pop()
        duration = bool(re.search(
            r"\b(?:dieu kien\b.*\bva\b.*\bthoi (?:han|gian)"
            r"|thoi (?:han|gian)\b.*\bva\b.*\bdieu kien)\b", q,
        ))
        return QuestionFocus(" ".join(words), "conditions", duration=duration)
    return QuestionFocus(question)


def facet_supported(kind: str, body_ascii: str) -> bool:
    """A topic match alone cannot answer when/who/how-much questions."""
    if kind == "trigger":
        return bool(re.search(r"\b(?:khi|neu|se bi|thi bi)\b|:\s*bi\b", body_ascii))
    if kind in {"timing", "payment_time"}:
        if kind == "payment_time" and not re.search(r"\b(?:chuyen khoan|chi tra|phat|thanh toan|tra tien)\b", body_ascii):
            return False
        return bool(re.search(
            r"\b\d+\s*(?:ngay|thang|tuan|nam|hoc ky|gio)\b"
            r"|\b(?:ngay|thang|tuan|nam|hoc ky)\s+(?:thu\s+)?\d+\b"
            r"|\b(?:dau|cuoi|hang|moi|tung)\s+(?:ngay|thang|tuan|nam|hoc ky)\b", body_ascii,
        ))
    if kind == "conditions":
        return bool(re.search(
            r">=|<=|≥|≤|\b(?:dieu kien|tieu chuan|chi xet|duoc xet|toi thieu|it nhat"
            r"|toi da|khong qua|khong duoc|khong bi|phai|da hoan thanh|tu\s+\d+)\b", body_ascii,
        ))
    if kind == "actor":
        return bool(re.search(
            r"->|→|\b(?:buoc|hoi dong|tap the|ca nhan|phong|khoa|giao vien|giang vien)\b"
            r".*\b(?:danh gia|duyet|cham|quyet dinh|thuc hien)\b", body_ascii,
        ))
    if kind == "amount":
        return bool(re.search(r"\d+(?:[.,]\d+)?\s*(?:%|(?:trieu\s+)?dong\b|vnd\b|vnd/thang\b)", body_ascii))
    return True


def reward_amount(body_ascii: str) -> tuple[str, Decimal] | None:
    match = re.search(r"\bthuong\s+(\d{1,12}(?:[.,]\d{1,4})?)\s*(%|dong\b|vnd\b)", body_ascii)
    return (match[2], Decimal(match[1].replace(",", "."))) if match else None


def _causal_parts(question: str) -> tuple[str, str]:
    words = re.findall(r"\w+", normalize(question).lower())
    forms = [strip_accents(word) for word in words]
    for index, word in enumerate(forms):
        if words[index] in {"vì", "vi", "do"} and index and forms[index - 1] != "don":
            return " ".join(words[:index]), without_phrases(" ".join(words[index + 1:]), (
                "trong trường hợp nào", "trường hợp nào", "thì sao", "không",
            ))
    return "", ""


def causal_focus(question: str) -> str:
    """An explicit 'because of X' needs evidence for X as a cause, not a result."""
    return _causal_parts(question)[1]


def causal_consequence(question: str) -> str:
    return _causal_parts(question)[0]


def condition_fragments(body: str) -> tuple[str, ...]:
    fragments = []
    for sentence in re.split(r"(?<!\d)[.;](?!\d)|\n", body):
        words = re.findall(r"\w+|>=|<=", sentence.lower())
        forms = [strip_accents(word) for word in words]
        for index, word in enumerate(forms):
            if words[index] in {"bị", "bi", "được", "duoc"} and index:
                fragments.append(" ".join(words[:index]))
            if words[index] in {"nếu", "neu", "khi", "vì", "vi", "do"} and (not index or forms[index - 1] != "don"):
                fragments.append(" ".join(words[index + 1:]))
    return tuple(fragment for fragment in fragments if fragment)
