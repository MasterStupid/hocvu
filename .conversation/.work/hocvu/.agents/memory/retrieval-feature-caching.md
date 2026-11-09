---
name: Retrieval feature caching
description: Why lexical precomputation is shared through chunks, not a global ID cache or serialized index metadata.
---

Keep precomputed lexical features attached to the actual chunk, immutable and runtime-only. Identify reuse by the text/heading inputs and helper implementation, never by the chunk ID alone.

**Why:** generation also uses evidence helpers without a searcher instance. Instance-only arrays would miss those callers; a global ID cache could retain deleted documents or reuse evidence for changed content. Runtime-only data preserves existing index/API serialization and lets old corpora be reclaimed.

**How to apply:** prepare features at index build/load and allow lazy preparation for standalone evidence/generation callers. Publish complete immutable values rather than mutating shared sets; do not introduce a global cache of user questions. Preserve separate representations for unexpanded support words, raw stopword adjacency, abbreviation support and expanded ranking phrases.

Judge performance against equivalent outputs, not a claimed percentage.

**Why:** making ranking phrases count as evidence can appear faster while weakening Vietnamese grounding. Moving work to build time also trades additional initialization work and memory for lower per-query CPU.

**How to apply:** compare scores/order, support/anchors, coverage, generated answers and citations before/after. Label BM25 CPU measurements separately from model inference, provider latency and full HTTP response time.
