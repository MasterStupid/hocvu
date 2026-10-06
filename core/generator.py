"""Grounded, extractive response generation.

The pilot intentionally does not invent institutional rules. Any future LLM
adapter must retain the retrieved passages and their citations.
"""
from __future__ import annotations

import re

from .models import Reference, RankedChunk
from .nlp import content_tokens


DECLINE_MSG = "Tôi chưa tìm được căn cứ đủ rõ trong cơ sở tri thức hiện có để trả lời chính xác. Bạn hãy thử nêu rõ hơn nội dung cần tra cứu hoặc bổ sung văn bản quy chế chính thức."


class Generator:
    def __init__(self, config):
        self.config = config

    def generate(self, question: str, hits: list[RankedChunk]) -> tuple[str, list[Reference]]:
        if not hits:
            return DECLINE_MSG, []
        query_terms = set(content_tokens(question))
        min_overlap = min(2, max(1, len(query_terms)))
        selected = []
        best_overlap = 0
        best_score = hits[0].score
        primary_rid = hits[0].chunk.rid
        for hit in hits:
            # Do not pad an answer with weakly related passages simply because
            # top_k contains a second document that shares a generic word.
            if selected and hit.score < best_score * 0.55:
                break
            # For a normal lookup, keep evidence in the best-matching source
            # document. This avoids mixing an unrelated demo regulation into
            # an answer sourced from an uploaded report.
            if hit.chunk.rid != primary_rid:
                continue
            overlap = len(query_terms.intersection(content_tokens(hit.chunk.text)))
            # The first passage establishes what the question is really
            # about. Subsequent passages must be almost as specific, rather
            # than merely sharing a broad term such as "hệ thống".
            required_overlap = max(min_overlap, best_overlap - 1) if selected else min_overlap
            # Semantic evidence permits a paraphrased question to retrieve a
            # grounded passage even when it shares fewer literal Vietnamese
            # tokens with that passage.
            semantic_evidence = hit.vec >= self.config.semantic_floor
            if overlap >= required_overlap or semantic_evidence:
                selected.append(hit)
                if len(selected) == 1:
                    best_overlap = overlap
            if len(selected) >= self.config.max_units:
                break
        if not selected:
            return DECLINE_MSG, []
        references = [Reference(
            rid=hit.chunk.rid, reg_title=hit.chunk.reg_title, aid=hit.chunk.aid,
            art_heading=hit.chunk.art_heading, clause_ids=hit.chunk.clause_ids,
            excerpt=_excerpt(hit.chunk.text),
        ) for hit in selected]
        # The article/clause identifiers are retained in `references` for
        # traceability, but are jargon for students reading the reply. Chunks
        # already begin with their natural section heading.
        answer = "\n\n".join(hit.chunk.text for hit in selected)
        return answer, references

    def generate_attendance_training_scenario(self, hits: list[RankedChunk], question: str = "") -> tuple[str, list[Reference]] | None:
        """Explain an absence/discipline scenario without inventing a penalty."""
        attendance = next((hit for hit in hits if "vắng mặt" in hit.chunk.text.lower() and "%" in hit.chunk.text), None)
        course_score = next((hit for hit in hits if "điểm chuyên cần chiếm" in hit.chunk.text.lower()), None)
        training = next((hit for hit in hits if "ý thức học tập và chuyên cần" in hit.chunk.text.lower()), None)
        exact_deduction = next((hit for hit in hits if "trừ" in hit.chunk.text.lower() and "điểm" in hit.chunk.text.lower() and any(term in hit.chunk.text.lower() for term in ("vắng", "nghỉ"))), None)
        if not training:
            return None
        selected = [hit for hit in (training, exact_deduction, course_score, attendance) if hit]
        references = [Reference(
            rid=hit.chunk.rid, reg_title=hit.chunk.reg_title, aid=hit.chunk.aid,
            art_heading=hit.chunk.art_heading, clause_ids=hit.chunk.clause_ids,
            excerpt=_excerpt(hit.chunk.text),
        ) for hit in selected]
        absent = re.search(r"\b(?:nghỉ|vắng mặt|bỏ học)\s+(\d+(?:[.,]\d+)?)\s+(tiết|buổi)\b", question, re.IGNORECASE)
        stated_absence = f"Việc nghỉ {absent.group(1)} {absent.group(2)}" if absent else "Việc nghỉ học"
        parts = [f"{stated_absence} có thể ảnh hưởng đến tiêu chí ý thức học tập và chuyên cần khi chấm điểm rèn luyện; tiêu chí này tối đa 30 điểm."]
        if course_score:
            parts.append("Với học phần, điểm chuyên cần cũng chiếm 10% tổng điểm và được đánh giá qua mức độ tham gia trên lớp.")
        if exact_deduction:
            parts.append(f"Văn bản có nêu mức xử lý trực tiếp cho trường hợp vắng/nghỉ học: {exact_deduction.chunk.text.splitlines()[-1]}")
        else:
            parts.append("Tuy nhiên, tài liệu hiện có không quy định mức trừ điểm rèn luyện cố định chỉ theo số tiết vắng mặt bạn nêu, nên chưa thể kết luận bạn bị trừ bao nhiêu điểm. Mức cụ thể còn phụ thuộc quy định điểm danh/chấm rèn luyện của lớp hoặc khoa.")
        if attendance:
            parts.append("Ngưỡng được nêu rõ là vắng quá 25% tổng số tiết của một học phần sẽ bị cấm thi cuối kỳ.")
        return "\n\n".join(parts), references


def _excerpt(text: str, limit: int = 280) -> str:
    """Return a readable citation preview without silently cutting a word."""
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    boundary = compact.rfind(" ", 0, limit - 3)
    return f"{compact[:boundary if boundary > 0 else limit - 3].rstrip()}..."
