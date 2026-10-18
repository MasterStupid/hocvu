---
name: Embedding cache lifecycle
description: Why passage vectors use whole-collection cache generations and retain older generations.
---

Treat a passage-vector cache as one ordered collection, not a collection of independently reusable rows. Retain older content-addressed generations unless an explicit, concurrency-safe cleanup policy is introduced.

**Why:** Row order determines which regulation receives a similarity score. Whole-collection identity deliberately favors safe invalidation over incremental reuse. Keeping generations avoids one server or CLI operation deleting a cache another operation still needs, and permits reuse after a configuration rollback. Disk usage is the accepted tradeoff until cleanup is implemented.

**How to apply:** Preserve ordering and full freshness/model identity when changing cache persistence. Any future pruning must coordinate with cache readers and writers and must never remove downloaded model weights or original documents.
