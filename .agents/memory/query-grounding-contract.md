---
name: Query grounding contract
description: Consistent normalization, question-specific evidence, and limits of numeric verdicts.
---

Retrieval and primary-passage validation must use the same expanded question meaning. Keep the original question separately for observed numbers and display. Remove request operators, not academic compound words or unknown features.

**Why:** validating the original wording after retrieving its normalized paraphrase rejected supported scoring questions. Conversely, treating receipt/condition framing as topic evidence selected scholarship payment text instead of eligibility. Removing individual words indiscriminately can corrupt terms such as “chuyên cần” and “công nhận”.

**How to apply:** test the selected article and statement, not merely a regulation-level hit. Preserve Vietnamese diacritics when recognizing framing as well as evidence, and keep unsupported named categories/features in the grounded topic.

Distinguish a conditional “khi nào ... bị ...” from a calendar or duration request. Recognize an explicit temporary study-break-and-return frame before applying generic absence synonyms; bare “nghỉ” must not become a formal leave request.

**Why:** a calendar-only evidence gate discarded a valid academic-warning threshold. Conversely, normalizing every “nghỉ” to absence lost the meaning of pausing study and returning later; treating every absence as formal leave would be equally unsafe.

**How to apply:** require the appropriate conditional or duration evidence in the source, preserve extra reasons and unknown features, and test missing-rule refusals. In unaccented questions, remove a grammatical operator as a phrase rather than dropping ambiguous words globally (“thì”/“thi”).

Preserve complementary evidence for conjoined requests such as conditions plus duration. Each passage must establish the shared subject and its own requested aspect; it need not establish every requested aspect alone.

**Why:** requiring an eligibility passage to also contain a deadline discarded valid conditions and prevented the deadline's separate article from being selected.

**How to apply:** keep shared-topic checks strict while tracking the additional aspect for citation selection. Preserve the passage ceiling and same-source constraints. Semantic paraphrases must not override an available individually grounded primary passage or bypass explicit feature/facet checks.

Evidence depends on what is asked. Document identity/effectivity can use validated title/version/date metadata. Ordinary policy predicates still need clause evidence. A document title may scope an evaluation procedure, but the procedure's operation and actors must be stated in its body.

**Why:** body-only checks lose legitimate metadata answers and implicitly scoped procedures; letting every title count as policy proof instead permits unrelated answers. Likewise, a topic match alone does not establish a payment date, an actor, a monetary amount, or a causal relationship.

**How to apply:** require the requested information type in the chosen source, retain validity filtering, and reject missing/invalid/future date evidence rather than inventing it.

Numeric eligibility verdicts compare stated student measurements with explicit source bounds. A positive numeric comparison is not confirmation that every nonnumeric condition is satisfied; penalty/reward totals remain subject to their separate explicit-rate rules.

**Why:** a valid lower-bound comparison does not establish all prerequisites, and a count of reprimands does not authorize assuming a per-occurrence deduction.

**How to apply:** preserve source directions, intervals, exceptions and decimal precision. Keep verdicts attached to the actual supporting citation; do not shift later paragraph-to-citation assignments.
