---
name: History evidence snapshots
description: Why restored answers must use the original evidence assessment rather than current retrieval or invented legacy defaults.
---

Saved answer presentation represents the evidence at the time of the original reply. Do not rerun retrieval or look up current regulations to reconstruct missing historical citations or confidence.

**Why:** regulations can change or disappear, and a regulation/article ID does not identify the exact cited clauses, excerpt or assessment. Recomputing from today's corpus can silently attribute different evidence to the old answer.

**How to apply:** retain the original presentation snapshot with newly accepted academic turns. Missing or corrupt legacy presentation must remain visibly unavailable, not become a fabricated weak/zero-source assessment or an asserted academic conclusion. Keep the existing grounded-only persistence and context policy.

Citation numbers such as `[1]` belong to an individual answer, not to the whole conversation. Keep each answer's source list separate when exporting, even when several answers use the same document.

**Why:** the user requires exports to retain each displayed turn's original evidence; repeated numbers can refer to different clauses or documents and must not be merged into a shared source.

**How to apply:** export the original citation-to-source mapping without looking up current documents, deduplicating across turns or guessing sources from legacy IDs.

New and restored greetings must remain ordinary chat messages, regardless of confidence or any card-shaped payload.

**Why:** a greeting makes no regulatory claim to assess. Showing an academic conclusion or “Căn cứ yếu · 0 nguồn” incorrectly treats it as an unsupported academic answer.
