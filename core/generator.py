"""Grounded, extractive response generation.

The pilot intentionally does not invent institutional rules. Any future LLM
adapter must retain the retrieved passages and their citations.
"""
from __future__ import annotations

import re
from decimal import Decimal, localcontext

from .models import Reference, RankedChunk
from .nlp import accented_content_tokens, content_tokens, normalize, strip_accents
from .scenarios import comparison_subjects, comparison_topic, is_version_comparison_query


DECLINE_MSG = "Tôi chưa tìm được căn cứ đủ rõ trong cơ sở tri thức hiện có để trả lời chính xác. Bạn hãy thử nêu rõ hơn nội dung cần tra cứu hoặc bổ sung văn bản quy chế chính thức."


class Generator:
    def __init__(self, config):
        self.config = config

    def generate(self, question: str, hits: list[RankedChunk], comparison: bool = False) -> tuple[str, list[Reference]]:
        if not hits:
            return DECLINE_MSG, []
        if comparison:
            if not is_version_comparison_query(question):
                selected = self.select_comparison_evidence(question, hits)
                if not selected:
                    return DECLINE_MSG, []
                subjects = comparison_subjects(question)
                answer = "\n\n".join(
                    f"{subject}:\n{hit.chunk.text}" for subject, hit in zip(subjects, selected)
                )
                if any(strip_accents(subject).lower().startswith("diem ") for subject in subjects):
                    if not all(self._has_scoring_rule(hit) for hit in selected):
                        answer += (
                            "\n\nLưu ý: nguồn hiện có chưa nêu đầy đủ cách tính điểm "
                            "cho cả hai nội dung, nên chưa thể kết luận sự khác biệt "
                            "về công thức chấm điểm."
                        )
                # One passage can explicitly cover both subjects. Quote it for
                # each side if needed, but never duplicate its citation.
                unique = {(hit.chunk.rid, hit.chunk.cid): hit for hit in selected}
                return answer, [self._reference(hit) for hit in unique.values()]
            compared = self._generate_comparison(question, hits)
            if compared:
                return compared
            # Never quietly answer a comparison as if both versions existed.
            topic = comparison_topic(question)
            from .searcher import HybridSearcher
            supported = [hit for hit in hits if HybridSearcher.has_specific_evidence(topic, [hit])]
            if not supported:
                return DECLINE_MSG, []
            best = supported[0]
            return (
                "Chưa đủ các phiên bản quy định liên quan để kết luận nội dung có thay đổi hay không. "
                f"Nguồn hiện có (phiên bản {best.chunk.version}):\n\n{best.chunk.text}",
                [self._reference(best)],
            )
        numeric = self._generate_repeated_unit_total(question, hits)
        if numeric:
            return numeric
        query_terms = set(content_tokens(question))
        min_overlap = min(2, max(1, len(query_terms)))
        selected = []
        best_overlap = 0
        best_score = 0.0
        primary_rid = None
        seen = set()
        from .searcher import HybridSearcher
        # Request framing must not make an unrelated clause count as new
        # subject evidence ("nhận" in payment instructions is not eligibility).
        topic = " ".join(
            word for word in HybridSearcher._raw_words(question)
            if strip_accents(word) not in {"dieu", "kien", "nhan"}
        ) if {"dieu", "kien"}.issubset(query_terms) else question
        topic = HybridSearcher._credit_quantity_topic(question) or topic
        topic_terms = {
            HybridSearcher._query_form(term) for term in accented_content_tokens(topic)
            if not HybridSearcher._is_non_specific(term)
        }
        covered_topic = set()
        for hit in hits:
            # Do not pad an answer with weakly related passages simply because
            # top_k contains a second document that shares a generic word.
            if selected and hit.score < best_score * 0.55:
                # Coverage reranking need not preserve raw-score order.
                continue
            # Lock the source only after a candidate actually qualifies.
            if primary_rid is not None and hit.chunk.rid != primary_rid:
                continue
            identity = (hit.chunk.rid, hit.chunk.cid)
            if identity in seen:
                continue
            overlap = len(query_terms.intersection(content_tokens(hit.chunk.text)))
            # Additional passages must stay close to the primary passage's
            # topic and independently support the question, not merely repeat
            # a generic heading or borrow evidence from the first clause.
            required_overlap = max(min_overlap, best_overlap - 1) if selected else min_overlap
            # Semantic evidence permits a paraphrased question to retrieve a
            # grounded passage even when it shares fewer literal Vietnamese
            # tokens with that passage.
            semantic_evidence = hit.vec >= self.config.semantic_floor
            if overlap >= required_overlap or semantic_evidence:
                if selected and not HybridSearcher.has_specific_evidence(question, [hit]):
                    continue
                supported_topic = topic_terms & HybridSearcher._supported_terms(topic, hit.chunk)
                if (
                    selected
                    and not any(item.chunk.aid == hit.chunk.aid for item in selected)
                    and not supported_topic - covered_topic
                ):
                    # More clauses from the same article may supply separate
                    # conditions. A different article must address an additional
                    # requested aspect, not swap graduation totals for project
                    # credits or scholarship eligibility for payment methods.
                    continue
                selected.append(hit)
                seen.add(identity)
                covered_topic.update(supported_topic)
                if len(selected) == 1:
                    best_overlap = overlap
                    best_score = hit.score
                    primary_rid = hit.chunk.rid
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

    @staticmethod
    def _reference(hit: RankedChunk) -> Reference:
        return Reference(
            rid=hit.chunk.rid, reg_title=hit.chunk.reg_title, aid=hit.chunk.aid,
            art_heading=hit.chunk.art_heading, clause_ids=hit.chunk.clause_ids,
            excerpt=_excerpt(hit.chunk.text),
        )

    def select_comparison_evidence(self, question: str, hits: list[RankedChunk]) -> list[RankedChunk]:
        """Ground each content subject independently, without grouping by rid."""
        from .searcher import HybridSearcher
        subjects = comparison_subjects(question)
        if len(subjects) != 2:
            return []
        terms = [accented_content_tokens(subject) for subject in subjects]
        forms = [set(HybridSearcher._query_forms(subject)) for subject in subjects]
        shared = forms[0] & forms[1]
        candidates = []
        for index, subject in enumerate(subjects):
            # Shared topic words cannot stand in for the distinguishing item:
            # a Giỏi clause is not evidence for Xuất sắc or an unknown category.
            distinct = forms[index] - forms[1 - index]
            # "Điểm thực tập" can be expressed as "Đánh giá ... (40%) ...".
            # Keep the normal coverage gate, but require the nominal subject,
            # not the introductory feature word, to be literally present.
            if len(terms[index]) > 1 and strip_accents(terms[index][0]) == "diem":
                distinct.discard(HybridSearcher._query_form(terms[index][0]))
            matches = [
                hit for hit in HybridSearcher.rerank_by_coverage(subject, hits)
                if HybridSearcher.has_specific_evidence(subject, [hit])
                and (distinct | shared).issubset(HybridSearcher._supported_terms(subject, hit.chunk))
                and (
                    hit.vec >= self.config.semantic_floor
                    or HybridSearcher.lexical_coverage(subject, hit) >= self.config.lexical_coverage_floor
                )
            ]
            if not matches:
                return []
            if strip_accents(terms[index][0]) == "diem":
                # "thời điểm đăng ký" is not a scoring rule, even though
                # literal coverage can rank it above "Đánh giá ... 40%/60%".
                matches.sort(key=self._has_scoring_rule, reverse=True)
            candidates.append(matches)
        # Prefer a complete pair from one regulation, but allow explicitly
        # named subjects to have independent sources when both are grounded.
        for left in candidates[0]:
            right = next((hit for hit in candidates[1] if hit.chunk.rid == left.chunk.rid), None)
            if right:
                return [left, right]
        if len(terms[1]) <= 2 and not shared:
            # A bare elliptical category ("Giỏi và Xuất sắc") must inherit
            # its source topic, not borrow the other half from an unrelated rule.
            return []
        return [candidates[0][0], candidates[1][0]]

    @staticmethod
    def _has_scoring_rule(hit: RankedChunk) -> bool:
        from .searcher import HybridSearcher
        body = strip_accents(HybridSearcher._clause_body(hit.chunk)).lower()
        return bool(re.search(
            r"\b(?:danh gia|cham diem|diem (?:hoc tap|trung binh|tich luy|ren luyen))\b",
            body,
        ))

    def _generate_comparison(self, question: str, hits: list[RankedChunk]) -> tuple[str, list[Reference]] | None:
        """Return one directly relevant passage per regulation for comparison."""
        ignored = {"quy", "dinh", "phien", "ban", "cu", "moi", "khac", "so", "sanh", "voi", "va"}
        topic = comparison_topic(question)
        topic_tokens = [term for term in content_tokens(topic) if term not in ignored and not re.fullmatch(r"20\d{2}", term)]
        topic_terms = set(topic_tokens)
        topic_phrases = {" ".join(topic_tokens[index:index + 2]) for index in range(len(topic_tokens) - 1)}
        by_regulation: dict[str, tuple[tuple[int, int, float], RankedChunk]] = {}
        from .searcher import HybridSearcher
        for hit in hits:
            if not HybridSearcher.has_specific_evidence(topic, [hit]):
                continue
            # A chunk repeats its article heading. For a comparison we need
            # the clause body to decide between neighbouring clauses under
            # one heading (for example "thi lại" vs "học lại").
            body = hit.chunk.text.split("\n", 1)[-1]
            tokens = content_tokens(body)
            overlap = len(topic_terms.intersection(tokens))
            phrase_hits = sum(phrase in " ".join(tokens) for phrase in topic_phrases)
            if not overlap:
                continue
            rank = (phrase_hits, overlap, hit.score)
            current = by_regulation.get(hit.chunk.rid)
            if current is None or rank > current[0]:
                by_regulation[hit.chunk.rid] = (rank, hit)
        ordered = [item[1] for item in sorted(by_regulation.values(), key=lambda item: item[0], reverse=True)]
        if not ordered:
            return None
        first = ordered[0]
        # A second document mentioning the subject is not necessarily another
        # version of the same rule (e.g. scholarship vs training-score rules).
        def family(hit):
            return re.sub(r"[-_]20\d{2}(?:$|[-_].*)", "", hit.chunk.rid)
        other = next((hit for hit in ordered[1:] if (
            family(hit) == family(first)
            and hit.chunk.version != first.chunk.version
        )), None)
        if other is None:
            return None
        selected = [first, other]
        lines = [f"{hit.chunk.version}: {hit.chunk.text}" for hit in selected]
        return "\n\n".join(lines), [self._reference(hit) for hit in selected]

    def _generate_repeated_unit_total(self, question: str, hits: list[RankedChunk]) -> tuple[str, list[Reference]] | None:
        """Compute only a requested point total from the primary grounded clause.

        A mention of a repetition count is not a request for arithmetic. Never
        search weaker hits for a rate that can override the primary rule.
        """
        query = strip_accents(normalize(question)).lower()
        counts = re.findall(r"(?<![\w.,+\-])(\d+)\s+lan\b", query)
        if (
            len(counts) != 1
            or not re.search(r"\bdiem\b", query)
            or not re.search(r"\b(?:bao nhieu|may|tong|tong cong)\b", query)
            or not hits
        ):
            return None
        from .searcher import HybridSearcher
        hit = hits[0]
        if not HybridSearcher.has_specific_evidence(question, [hit]):
            return None
        # The direction must be explicit in the same clause as the rate.
        # Ambiguous/multiple rates remain extractive rather than being guessed.
        body = HybridSearcher._clause_body(hit.chunk)
        rates = list(re.finditer(
            r"\b(?P<direction>cộng|trừ)\s+(?P<rate>\d+(?:[.,]\d+)?)\s*điểm\s*/\s*lần\b",
            body, re.IGNORECASE,
        ))
        if len(rates) != 1:
            return None
        unit = rates[0]
        # Do not turn a negated rule ("không được cộng ...") into a reward.
        sentence_start = max(body.rfind(".", 0, unit.start()),
                             body.rfind(";", 0, unit.start()),
                             body.rfind("\n", 0, unit.start())) + 1
        prefix = body[sentence_start:unit.start()].lower()
        if re.search(r"\b(?:không|chưa|chẳng)\b", prefix):
            return None
        occurrences = int(counts[0])
        rate_text = unit.group("rate").replace(",", ".")
        with localcontext() as context:
            context.prec = max(28, len(counts[0]) + len(rate_text))
            total = Decimal(counts[0]) * Decimal(rate_text)
        cap = re.search(r"\btối đa\s+(\d+(?:[.,]\d+)?)\s*điểm\b", body, re.IGNORECASE)
        if cap and total > Decimal(cap.group(1).replace(",", ".")):
            # A category cap is not an unlimited linear rule. Quote the
            # original clause rather than claiming an unsupported total.
            return None
        total_text = format(total, "f")
        if "." in total_text:
            total_text = total_text.rstrip("0").rstrip(".")
        action = "được cộng" if unit.group("direction").lower() == "cộng" else "bị trừ"
        return (
            f"Theo quy định, mỗi lần {action} {unit.group('rate')} điểm. "
            f"{occurrences} lần × {unit.group('rate')} điểm/lần = {total_text} điểm {action}.",
            [self._reference(hit)],
        )

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
