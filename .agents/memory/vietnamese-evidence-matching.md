---
name: Vietnamese evidence matching rules
description: Why retrieval/abstention compares words with diacritics and treats abbreviations as phrases; what tuning approaches failed.
---
- Evidence checks (coverage, specificity, BM25 terms) compare a query word with diacritics when the student typed them, and on the unaccented form otherwise. Tone placement is ignored ("hoà" = "hòa").
  **Why:** stripping accents merged unrelated words ("bóng đá" vs "học bổng … tối đa"), so off-topic questions were answered.
- An abbreviation in the text (ĐRL, HBKKHT) supports a query word only when the query has two consecutive words of its expansion.
  **Why:** "điểm" from "điểm danh" was credited to clauses mentioning ĐRL, making the proxy-attendance question cite the training-score regulation.
- Do not down-weight article-heading words in ranking. It was tried and broke terse clauses whose heading carries the topic ("Xếp loại điểm rèn luyện", "Quy trình đánh giá").
- Unaccented questions: the specificity gate also needs one "anchor" word — typed with accents, or found next to its query neighbour in the clause (numbers never anchor).
  **Why:** "giai bong da" matched "học bổng … tối đa". Requiring *every* unaccented word to be in a phrase was tried and refused many real paraphrases ("diem duoi bao nhieu thi phai hoc lai").
- Unaccented "da" is not a filler word: it can be "dạ", "đá" or "đa".
- For yes/no question focus, require an anchored predicate term rather than imposing a second half-coverage threshold on the predicate.
  **Why:** a half-coverage threshold rejected the valid graduation paraphrase "Học lại 15% tín chỉ có ảnh hưởng đến bằng tốt nghiệp không?": the rule says "tốt nghiệp" but not "ảnh hưởng" or "bằng".
  **How to apply:** keep the whole-query specificity threshold; use predicate support to stop a long matching subject from hiding a completely unsupported requested feature.
- How to apply: before changing ranking, compare answers and citations for the evaluation set, the suggestion questions, and paraphrases.
