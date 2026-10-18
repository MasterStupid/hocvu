---
name: Vietnamese evidence matching rules
description: Why retrieval/abstention compares words with diacritics and treats abbreviations as phrases; what tuning approaches failed.
---
- Evidence checks (coverage, specificity, BM25 terms) compare a query word with diacritics when the student typed them, and on the unaccented form otherwise. Tone placement is ignored ("hoà" = "hòa").
  **Why:** stripping accents merged unrelated words ("bóng đá" vs "học bổng … tối đa"), so off-topic questions were answered.
- An abbreviation in the text (ĐRL, HBKKHT) supports a query word only when the query has two consecutive words of its expansion.
  **Why:** "điểm" from "điểm danh" was credited to clauses mentioning ĐRL, making the proxy-attendance question cite the training-score regulation.
- Do not down-weight article-heading words in ranking. It was tried and broke terse clauses whose heading carries the topic ("Xếp loại điểm rèn luyện", "Quy trình đánh giá").
- Known limit: fully unaccented ambiguous questions (e.g. "giai bong da") can still match "học bổng" text.
- How to apply: before changing ranking, compare answers and citations for the evaluation set, the suggestion questions, and paraphrases.
