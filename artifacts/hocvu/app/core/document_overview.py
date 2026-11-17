"""Explicit document overviews, kept separate from policy evidence gates."""
import re
import unicodedata
from datetime import date

from .cards import build_card
from .generator import DECLINE_MSG
from .models import RankedChunk, Reference


def overview_request(question):
    match = re.fullmatch(
        r'Văn bản ["“](.+?)["”](?: \(mã ([^()\n]+)\))? quy định những gì\?',
        question.strip(), re.IGNORECASE,
    )
    return match.groups() if match else None


def answer_overview(request, searcher, ref_date):
    title, rid = request
    key = lambda text: " ".join(unicodedata.normalize("NFC", text).casefold().split())
    documents = {}
    for chunk in searcher.chunks:
        if key(chunk.reg_title) != key(title) or (rid and chunk.rid != rid):
            continue
        try:
            date.fromisoformat(chunk.valid_from)
            if chunk.valid_until:
                if date.fromisoformat(chunk.valid_until) < date.fromisoformat(chunk.valid_from):
                    continue
        except (TypeError, ValueError):
            continue
        # A title alone must not silently select an expired/future version.
        if not rid and not searcher._is_valid(chunk, ref_date):
            continue
        documents.setdefault(chunk.rid, []).append(chunk)
    if len(documents) != 1:
        return DECLINE_MSG, [], [], 0.0
    chunks = next(iter(documents.values()))
    selected, articles = [], set()
    for chunk in chunks:
        if chunk.aid in articles or not chunk.text.strip():
            continue
        articles.add(chunk.aid)
        selected.append(chunk)
        if len(selected) == 6:
            break
    if not selected:
        return DECLINE_MSG, [], [], 0.0
    first = selected[0]
    lines = [f'Văn bản “{first.reg_title}” ({first.rid}, phiên bản {first.version}) có các nội dung sau trong phần đã lập chỉ mục:']
    if not searcher._is_valid(first, ref_date):
        lines.append("Lưu ý: văn bản này không có hiệu lực tại ngày tra cứu; phần dưới chỉ giới thiệu nội dung, không dùng để kết luận quy định đang áp dụng.")
    references, hits = [], []
    for chunk in selected:
        # Quote a bounded source passage, not an invented document summary.
        excerpt = chunk.text.strip()
        if len(excerpt) > 700:
            boundary = excerpt.rfind(" ", 0, 700)
            excerpt = excerpt[:boundary if boundary > 0 else 700] + "…"
        lines.append(f"{chunk.aid} — {chunk.art_heading}:\n“{excerpt}”")
        references.append(Reference(
            rid=chunk.rid, reg_title=chunk.reg_title, aid=chunk.aid,
            art_heading=chunk.art_heading, clause_ids=chunk.clause_ids,
            excerpt=excerpt,
        ))
        hits.append(RankedChunk(chunk, score=1.0))
    lines.append("Đây là phần giới thiệu trích từ tối đa 6 điều đã lập chỉ mục, không phải bản tóm tắt đầy đủ. Bạn có thể hỏi cụ thể về từng nội dung để kiểm tra điều kiện và ngoại lệ.")
    return "\n\n".join(lines), references, hits, 1.0


def overview_card(answer, references, hits, confidence):
    card = build_card(answer, references, hits, confidence)
    passages = {
        f"{hit.chunk.aid} — {hit.chunk.art_heading}:\n“{reference.excerpt}”": index
        for index, (hit, reference) in enumerate(zip(hits, references), 1)
    }
    card["verdict_segments"] = [
        {"text": paragraph, "cites": [passages[paragraph]] if paragraph in passages else []}
        for paragraph in answer.split("\n\n") if paragraph.strip()
    ]
    return card
