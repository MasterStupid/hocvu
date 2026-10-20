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
- Descriptive feature/location questions need the same separate focus check: a matching location alone does not support the feature being asked about.
  **Why:** "Wifi ở ký túc xá thế nào?" passed whole-query coverage on the dormitory words despite no wifi evidence.
  **How to apply:** recognize question structure with accent-aware markers, not topic blacklists; require whole-query and focus support in the same clause, and allow new supporting documents. Descriptive asks must support their leading specific topic even when a preposition is omitted; check it with its neighbours intact so abbreviation expansions still work. Keep the focus-level anchor, and distinguish generic request prefixes such as "chính sách" from the subject itself.
- For focused yes/no or descriptive asks, keep the primary answer passage individually supported, not merely the result pool.
  **Why:** a diploma-issuance clause can outrank the graduation-classification rule on “bằng tốt nghiệp”, while the later rule supplies all the evidence needed to pass the pool-level gate. Applying individual-evidence priority to every query instead broke scholarship eligibility ranking because generic request words are intentionally excluded from its topic ranking.
  **How to apply:** preserve ordinary eligibility/quantity ranking and the existing evidence thresholds; test both the article cited and the consequence stated, not just the regulation identifier.
- Ordinary answers may use multiple clauses, but the passage limit is a ceiling, not a quota.
  **Why:** simply permitting more passages mixed scholarship payment instructions into eligibility answers and project credits into graduation totals. Generic framing words can falsely make the extra article look complementary.
  **How to apply:** independently ground added clauses; another article must cover an additional requested aspect. Interpret eligibility/quantity framing consistently with retrieval ranking, rather than counting words such as “nhận” or “hệ” as new subject evidence.
- How to apply: before changing ranking, compare answers and citations for the evaluation set, the suggestion questions, and paraphrases.
- Version-comparison framing is not itself documentary evidence, but removing it must preserve descriptive subject/focus checks.
  **Why:** requiring clauses to repeat “thay đổi giữa các phiên bản” falsely refused supported training-score questions; reducing a query to bare topic words instead let unsupported wifi questions pass on dormitory words.
  **How to apply:** retain the requested feature and accent-aware evidence gates when extracting a comparison topic. For version comparisons, compare distinct versions of the same regulation, not merely two documents mentioning the topic; with only one version, cite what is known and explicitly say change cannot be established.
- Content comparisons do not imply historical access or require different source documents.
  **Why:** scholarship categories and internship/project rules can share one regulation. Requiring different documents either loses one side or substitutes unrelated graduation ranks for scholarship criteria.
  **How to apply:** ground both requested subjects and their shared topic separately. Do not borrow a missing category from another topic. If a source supplies credits but not a grading formula, quote the known rule and explicitly disclose the missing metric rather than presenting the two as equivalent.
- Arithmetic explanations must remain subordinate to the primary rule and preserve source-stated direction.
  **Why:** scanning the whole retrieval pool for any per-occurrence rate replaced dismissal after repeated academic warnings with training points, and hardcoded reward language turned a penalty into a reward.
  **How to apply:** calculate only requested point totals from the individually supported primary clause, with an explicit unambiguous rate/direction. Quote the source instead when negation, multiple rates, or a source cap makes linear multiplication unsafe.
- Conversation history must not supply evidence for a new, unsupported subject; a discourse connective is not an anaphoric reference.
  **Why:** short independent asks such as “Đồ án là gì?” and “Học phí ra sao” were contaminated by the preceding topic. Conversely, generic “Còn điều kiện nào khác?” can retrieve the conditions of an entirely unrelated regulation.
  **How to apply:** preserve independent topic changes, resolve actual references against a grounded antecedent, and refuse unresolved references. Only BM25 follow-ups with successfully resolved context may use the 0.40 floor (or the configured floor if lower); retain specificity checks and the semantic floor. Do not use a prior refusal or greeting as documentary context.
