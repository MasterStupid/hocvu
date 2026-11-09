"""Small, transparent query understanding rules for common student scenarios."""
from __future__ import annotations

import re

from .nlp import accent_key, expand_academic_terms, normalize, strip_accents


def is_attendance_training_scenario(question: str) -> bool:
    q = strip_accents(normalize(question)).lower()
    def has_phrase(phrase: str) -> bool:
        return bool(re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", q))
    mentions_absence = any(has_phrase(term) for term in ("nghi", "vang mat", "bo hoc"))
    mentions_class_time = any(has_phrase(term) for term in ("tiet", "buoi hoc", "di hoc"))
    mentions_training = has_phrase("ren luyen") or has_phrase("drl")
    return mentions_absence and mentions_class_time and mentions_training


def _matches_follow_up_phrase(words: list[str], phrase: str, start: int = 0) -> bool:
    markers = phrase.split()
    candidate = words[start:start + len(markers)]
    return len(candidate) == len(markers) and all(
        accent_key(word) == accent_key(marker) or word == strip_accents(marker)
        for word, marker in zip(candidate, markers)
    )


def is_context_dependent(question: str) -> bool:
    """References/ellipses lack a standalone subject, even if words retrieve hits."""
    words = re.findall(r"\w+", normalize(question).lower())
    # A whole reference phrase is required: "đồ" is not the pronoun "đó",
    # and a final "không"/"sao" says nothing about the question's subject.
    for noun in ("cái", "điều", "việc", "trường hợp", "quy định", "mức", "khoản"):
        for demonstrative in ("đó", "này", "ấy", "kia"):
            if any(_matches_follow_up_phrase(words, f"{noun} {demonstrative}", index)
                   for index in range(len(words))):
                return True
    # A dimension without a subject ("Thế còn thời gian tối đa?") needs its
    # antecedent; a new named subject ("Thế còn học phí?") does not. Match the
    # whole remaining phrase so "thời gian thực tập" stays independent.
    facet_words = words
    for prefix in ("thế còn", "vậy còn", "còn"):
        if _matches_follow_up_phrase(words, prefix):
            facet_words = words[len(prefix.split()):]
            break
    for facet in (
        "thời gian", "thời gian tối đa", "thời gian tối thiểu", "thời hạn",
        "thời hạn tối đa", "thời hạn tối thiểu", "điều kiện", "mức tối đa", "mức tối thiểu",
    ):
        for ending in ("", "là bao lâu", "bao lâu", "là bao nhiêu", "bao nhiêu", "thế nào"):
            phrase = f"{facet} {ending}".strip()
            if len(facet_words) == len(phrase.split()) and _matches_follow_up_phrase(facet_words, phrase):
                return True
    ellipses = (
        "còn điều kiện", "còn điều kiện nào khác", "còn trường hợp",
        "còn trường hợp nào khác", "còn gì", "còn gì nữa", "còn nữa không",
        "nói rõ hơn", "cụ thể hơn", "thế còn", "vậy còn", "nếu vậy", "nếu thế",
        "vậy thì", "thế thì", "tại sao", "vì sao", "được không", "thế nào",
        "như thế nào", "ra sao", "vậy sao", "sao vậy", "sao thế", "đó là gì",
        "bao nhiêu", "mấy lần",
    )
    variants = [words]
    if words and _matches_follow_up_phrase(words, "không", len(words) - 1):
        variants.append(words[:-1])
    return any(len(candidate) == len(phrase.split()) and _matches_follow_up_phrase(candidate, phrase)
               for candidate in variants for phrase in ellipses)


def is_contextual_follow_up(question: str) -> bool:
    """Recognise reference phrases or discourse prefixes, not isolated particles."""
    if is_context_dependent(question):
        return True
    words = re.findall(r"\w+", normalize(question).lower())
    prefixes = (
        "còn điều kiện", "còn trường hợp", "thế còn", "nói rõ hơn", "cụ thể hơn",
        "vậy còn", "vậy nếu", "nếu vậy", "nếu thế", "vậy thì", "thế thì",
    )
    return any(_matches_follow_up_phrase(words, phrase) for phrase in prefixes)


def is_historical_query(question: str) -> bool:
    """Whether the user explicitly asks to inspect a superseded regulation."""
    q = strip_accents(normalize(question)).lower()
    return any(phrase in q for phrase in ("quy dinh cu", "ban cu", "phien ban cu", "nam 2024", "2024"))


def is_comparison_query(question: str) -> bool:
    q = strip_accents(normalize(question)).lower()
    years = re.findall(r"\b20\d{2}\b", q)
    return len(set(years)) >= 2 or any(phrase in q for phrase in (
        "so sanh", "khac gi", "khac nhau", "doi chieu", "khac biet",
        "giua cac phien ban", "giua hai phien ban", "qua cac phien ban",
    )) or bool(re.search(
        r"\b(?:ban|quy dinh|van ban) (?:cu va (?:(?:ban|quy dinh|van ban) )?moi"
        r"|moi va (?:(?:ban|quy dinh|van ban) )?cu)\b", q,
    ))


def is_version_comparison_query(question: str) -> bool:
    """Only explicit version/history comparisons may include expired rules."""
    if not is_comparison_query(question):
        return False
    q = strip_accents(normalize(question)).lower()
    return (
        len(set(re.findall(r"\b20\d{2}\b", q))) >= 2
        or bool(re.search(r"\bphien ban\b", q))
        or bool(re.search(r"\b(?:quy dinh|van ban|ban) (?:cu|moi)\b", q))
    )


def comparison_subjects(question: str) -> tuple[str, ...]:
    """Extract two content subjects, retaining accents and shared category names.

    This deliberately handles explicit pairs, not arbitrary conjunctions in a
    long question. An unparseable comparison must not become a version lookup
    or silently fall back to answering just one side.
    """
    if not is_comparison_query(question) or is_version_comparison_query(question):
        return ()
    words = re.findall(r"\w+", normalize(question))

    def forms():
        return [strip_accents(word).lower() for word in words]

    for prefix in (
        "su khac biet giua", "khac biet giua", "so sanh giua",
        "doi chieu giua", "so sanh", "doi chieu",
    ):
        marker = prefix.split()
        if forms()[:len(marker)] == marker:
            words = words[len(marker):]
            break
    # Remove only the comparison's trailing question framing.
    for ending in (
        "co gi khac nhau", "khac nhau nhu the nao", "khac nhau the nao",
        "khac nhau ra sao", "khac nhau", "khac gi nhau", "khac biet the nao",
    ):
        marker = ending.split()
        if forms()[-len(marker):] == marker:
            words = words[:-len(marker)]
            break
    current = forms()
    separators = [(index, 1) for index, word in enumerate(current) if word in {"va", "voi"}]
    if not separators:
        separators = [(index, 2) for index in range(len(current) - 1)
                      if current[index:index + 2] == ["khac", "gi"]]
    if len(separators) != 1:
        return ()
    index, width = separators[0]
    left, right = words[:index], words[index + width:]
    if not left or not right:
        return ()
    # "học bổng loại Giỏi và Xuất sắc" names two scholarship categories,
    # not a scholarship and any unrelated rule containing "Xuất sắc".
    left_forms = [strip_accents(word).lower() for word in left]
    category = next((i for i in range(len(left_forms) - 1, -1, -1)
                     if left_forms[i] in {"loai", "hang", "muc", "nhom", "he"}), None)
    if category is not None and len(right) <= 2:
        right = left[:category + 1] + right
    return " ".join(left), " ".join(right)


def comparison_topic(question: str) -> str:
    """Remove version-comparison framing, not the subject or its predicates.

    Keep accents for the ordinary evidence gates. In particular an unsupported
    feature such as wifi must not be hidden by a supported location.
    """
    if not is_version_comparison_query(question):
        return question
    from .question_focus import without_phrases
    # Years and version operators scope the comparison, not its policy topic.
    # Everything else, especially unsupported requested features, is retained.
    topic = re.sub(r"\b(?:năm\s+|nam\s+)?20\d{2}\b", " ", normalize(question), flags=re.IGNORECASE)
    topic = without_phrases(topic, (
        "giữa các phiên bản quy định", "giữa hai phiên bản quy định",
        "qua các phiên bản quy định", "giữa các phiên bản", "giữa hai phiên bản",
        "qua các phiên bản", "bản cũ và bản mới", "bản mới và bản cũ",
        "quy định cũ và mới", "văn bản cũ và mới", "bản cũ và mới",
        "quy định mới và cũ", "văn bản mới và cũ", "bản mới và cũ",
        "khác nhau như thế nào", "khác nhau ra sao", "khác nhau thế nào",
        "có thay đổi", "thay đổi", "có khác nhau", "khác nhau",
        "khác gì", "so sánh", "đối chiếu",
    ))
    return topic + " như thế nào"


def expand_retrieval_query(question: str) -> str:
    """Add concepts implied by a student scenario, without altering its meaning."""
    expanded = expand_academic_terms(question)
    if is_attendance_training_scenario(expanded):
        return f"{expanded} vắng mặt điểm danh chuyên cần ý thức học tập điểm rèn luyện"
    return expanded
