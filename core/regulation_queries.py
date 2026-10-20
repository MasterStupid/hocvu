"""Ground document identity/effectivity answers in validated document metadata."""
from datetime import date

from .generator import DECLINE_MSG
from .models import RankedChunk, Reference
from .nlp import accented_content_tokens


def answer_metadata(focus, searcher, ref_date):
    terms = {searcher._query_form(term) for term in accented_content_tokens(focus.topic)
             if not searcher._is_non_specific(term)}
    if not terms:
        return DECLINE_MSG, [], [], 0.0
    documents = {}
    for chunk in searcher.chunks:
        # Neither a future rule nor malformed metadata establishes current law.
        if not chunk.valid_from or not searcher._is_valid(chunk, ref_date):
            continue
        try:
            date.fromisoformat(chunk.valid_from)
        except (TypeError, ValueError):
            continue
        title = searcher._chunk_features(chunk).title
        supported, anchored = searcher._support_from_features(
            focus.topic, title.words, title.pairs, title.aliases,
        )
        if not terms <= supported or not terms & anchored:
            continue
        # Prefer an actual effectivity clause as well as the metadata snapshot.
        body = searcher._chunk_features(chunk).body_ascii
        rank = ("hieu luc" in body, chunk.valid_from)
        if chunk.rid not in documents or rank > documents[chunk.rid][0]:
            documents[chunk.rid] = (rank, chunk)
    if not documents:
        return DECLINE_MSG, [], [], 0.0
    ordered = sorted(documents.values(), key=lambda item: (item[1].valid_from, item[1].rid), reverse=True)
    # Do not silently choose a single "current" version if metadata permits
    # several at the requested date. Report all matches, rather than guess.
    answers, references, hits = [], [], []
    for _, chunk in ordered:
        validity = f"có hiệu lực từ {chunk.valid_from}"
        if chunk.valid_until:
            validity += f" đến hết {chunk.valid_until}"
        line = f"{chunk.reg_title} — {chunk.rid}, phiên bản {chunk.version}, {validity}."
        if focus.kind == "metadata_current":
            line += f" Văn bản này có hiệu lực tại ngày tra cứu {ref_date}."
        answers.append(line)
        references.append(Reference(
            rid=chunk.rid, reg_title=chunk.reg_title, aid=chunk.aid,
            art_heading=chunk.art_heading, clause_ids=chunk.clause_ids,
            excerpt=f"Thông tin văn bản: {line}\n{chunk.text[:280]}",
        ))
        hits.append(RankedChunk(chunk, score=1.0))
    return "\n\n".join(answers), references, hits, 1.0
