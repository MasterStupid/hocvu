"""Compare explicit student measurements with explicit, conjunctive bounds.

This does not infer per-occurrence rates, waive conditions, or derive a rule
from neighbouring passages. An alternative/exception leaves the reply extractive.
"""
from decimal import Decimal
import re

from .nlp import normalize, strip_accents


_NUMBER = r"[-+]?\d+(?:[.,]\d+)?"
_MEASURES = (
    ("TOEIC", r"\btoeic\b"),
    ("GPA", r"\b(?:gpa|diem trung binh(?: tich luy)?|diem hoc tap)\b"),
    ("tín chỉ", r"\btin chi(?: tich luy)?\b"),
    ("điểm rèn luyện", r"\b(?:diem ren luyen|drl)\b"),
)
_BOUND = re.compile(
    rf"(?P<op>toi thieu|it nhat|khong duoi|tu|toi da|nhieu nhat|khong qua|>=|<=|≥|≤|tren|duoi|>|<)"
    rf"\s*(?P<value>{_NUMBER})(?!\w|[.,]\d)",
)


def _decimal(value):
    return Decimal(value.replace(",", "."))


def _observed(question: str, measure: str):
    # Both "TOEIC 400" and "400 điểm TOEIC"; similarly "35 tín chỉ".
    patterns = (
        rf"(?:{measure})\s*(?:(?:cua em|cua minh|dat|la|duoc|:|=)\s*)*(?P<value>{_NUMBER})(?!\w|[.,]\d)",
        rf"(?<![\w.,+\-])(?P<value>{_NUMBER})\s*(?:diem\s+)?(?:{measure})",
    )
    values = {_decimal(match["value"]) for pattern in patterns for match in re.finditer(pattern, question)}
    # Conflicting/ambiguous observations must not become a definite verdict.
    return next(iter(values)) if len(values) == 1 else None


def numeric_verdict(question: str, primary_body: str) -> str:
    q = strip_accents(normalize(question)).lower()
    if not re.search(r"\b(?:du dieu kien|co duoc)\b", q):
        return ""
    body = strip_accents(normalize(primary_body)).lower()
    if re.search(r"\b(?:hoac|ngoai tru|tru khi|dac biet|khong yeu cau|khong can|khong bat buoc|vi du)\b", body):
        return ""
    checked = []
    failures = []
    for label, measure in _MEASURES:
        observed = _observed(q, measure)
        if observed is None:
            continue
        for segment in re.split(r"\s+va\s+|;|(?<!\d)\.(?!\d)", body):
            if not re.search(measure, segment):
                continue
            # A segment mentioning two measures cannot safely assign one bound.
            if sum(bool(re.search(pattern, segment)) for _, pattern in _MEASURES) != 1:
                continue
            bounds = [(match["op"], _decimal(match["value"])) for match in _BOUND.finditer(segment)]
            interval = re.search(rf"\btu\s*({_NUMBER})\s+den\s*({_NUMBER})(?!\w|[.,]\d)", segment)
            if interval:
                bounds = [(">=", _decimal(interval[1])), ("<=", _decimal(interval[2]))]
            for operator, threshold in bounds:
                if operator in {"toi thieu", "it nhat", "khong duoi", "tu", ">=", "≥"}:
                    symbol, met = ">=", observed >= threshold
                    failed_symbol = "<"
                elif operator in {"toi da", "nhieu nhat", "khong qua", "<=", "≤"}:
                    symbol, met = "<=", observed <= threshold
                    failed_symbol = ">"
                elif operator in {"tren", ">"}:
                    symbol, met = ">", observed > threshold
                    failed_symbol = "<="
                else:
                    symbol, met = "<", observed < threshold
                    failed_symbol = ">="
                detail = f"{label} {observed} {symbol if met else failed_symbol} {threshold}"
                checked.append(detail)
                if not met:
                    failures.append(detail)
    if failures:
        return "Không đủ điều kiện theo ngưỡng được nêu trong quy định: " + "; ".join(failures) + "."
    if checked:
        return (
            "Đáp ứng các ngưỡng số đã đối chiếu: " + "; ".join(checked)
            + ". Kết luận này chỉ áp dụng cho các ngưỡng số đã kiểm tra, không thay thế các điều kiện khác."
        )
    return ""
