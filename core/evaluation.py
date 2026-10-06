"""Repeatable offline evaluation for the proposal's RAG quality metric."""
from __future__ import annotations

import json
from pathlib import Path

from .corpus import build_corpus, build_qa


def evaluate(engine, output_path: Path) -> dict:
    """Measure whether a returned citation belongs to the expected regulation.

    This is a retrieval-grounding metric, not a claim of generative answer
    correctness. STT WER and human TTS usability are collected separately in a
    real pilot because they require recorded speech and participant ratings.
    """
    questions = build_qa(build_corpus(seed=engine.config.seed), seed=engine.config.seed)
    rows = []
    grounded_correct = refusals_correct = 0
    for item in questions:
        # Evaluation must not pollute real user dialogue history.
        response = engine.ask(item.question, session_id=f"evaluation-{item.qid}", record_session=False)
        cited = {reference.rid for reference in response.references}
        if item.should_refuse:
            correct = response.refused
            refusals_correct += int(correct)
        else:
            correct = bool(cited.intersection(item.source_rids)) and not response.refused
            grounded_correct += int(correct)
        rows.append({"qid": item.qid, "question": item.question, "expected_rids": item.source_rids, "refused": response.refused, "cited_rids": sorted(cited), "correct": correct})
    in_scope = [item for item in questions if not item.should_refuse]
    out_scope = [item for item in questions if item.should_refuse]
    report = {
        "total": len(questions),
        "grounded_retrieval_accuracy": round(grounded_correct / max(1, len(in_scope)), 4),
        "out_of_scope_refusal_accuracy": round(refusals_correct / max(1, len(out_scope)), 4),
        "notes": [
            "Chỉ số đo độ đúng của văn bản được trích dẫn đối với bộ dữ liệu minh họa.",
            "Đánh giá STT WER, chất lượng TTS, độ trễ và sự hài lòng cần thực hiện với dữ liệu và người dùng thật.",
        ],
        "rows": rows,
    }
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
