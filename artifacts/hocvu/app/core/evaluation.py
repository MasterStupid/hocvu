"""Repeatable offline evaluation for the proposal's RAG quality metric."""
from __future__ import annotations

import json
from pathlib import Path

from .corpus import build_corpus, build_qa


def evaluate(engine, output_path: Path) -> dict:
    """Measure regulation-level and article-level citation grounding.

    The legacy metric accepts any citation to an expected regulation. The
    article metric requires a single reference to match both the expected
    regulation and article; separate references cannot supply each half.
    These are retrieval-grounding metrics, not claims of generative answer
    correctness or that every claim/citation is supported. STT WER and human
    TTS usability are collected separately in a real pilot.
    """
    questions = build_qa(build_corpus(seed=engine.config.seed), seed=engine.config.seed)
    rows = []
    grounded_correct = article_correct_count = refusals_correct = 0
    for item in questions:
        # Evaluation must not pollute real user dialogue history.
        # An evaluation item must be independent of any old browser/session
        # data that happens to share its deterministic identifier.
        response = engine.ask(item.question, session_id=f"evaluation-{item.qid}", use_context=False, record_session=False)
        cited = {reference.rid for reference in response.references}
        # Refusal items and legacy questions without article annotations do
        # not belong in the article metric's denominator.
        article_correct = None
        if item.should_refuse:
            correct = response.refused
            refusals_correct += int(correct)
        else:
            correct = bool(cited.intersection(item.source_rids)) and not response.refused
            grounded_correct += int(correct)
            if item.source_aids:
                article_correct = not response.refused and any(
                    reference.rid in item.source_rids
                    and reference.aid in item.source_aids
                    for reference in response.references
                )
                article_correct_count += int(article_correct)
        rows.append({
            "qid": item.qid,
            "question": item.question,
            "expected_rids": item.source_rids,
            "expected_aids": item.source_aids,
            "refused": response.refused,
            "cited_rids": sorted(cited),
            "cited_articles": [
                {"rid": rid, "aid": aid}
                for rid, aid in sorted({(ref.rid, ref.aid) for ref in response.references})
            ],
            "correct": correct,
            "article_correct": article_correct,
        })
    in_scope = [item for item in questions if not item.should_refuse]
    out_scope = [item for item in questions if item.should_refuse]
    article_total = sum(bool(item.source_aids) for item in in_scope)
    report = {
        "total": len(questions),
        "grounded_retrieval_accuracy": round(grounded_correct / max(1, len(in_scope)), 4),
        "article_grounded_retrieval_accuracy": round(article_correct_count / max(1, article_total), 4),
        "article_grounded_retrieval_total": article_total,
        "out_of_scope_refusal_accuracy": round(refusals_correct / max(1, len(out_scope)), 4),
        "notes": [
            "Chỉ số đo độ đúng của văn bản được trích dẫn đối với bộ dữ liệu minh họa.",
            "Chỉ số theo điều yêu cầu cùng một trích dẫn khớp cả văn bản và điều nguồn; chỉ tính câu hỏi có điều nguồn.",
            "Đánh giá STT WER, chất lượng TTS, độ trễ và sự hài lòng cần thực hiện với dữ liệu và người dùng thật.",
        ],
        "rows": rows,
    }
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
