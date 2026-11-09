---
name: Local OCR privacy
description: Privacy boundary between document extraction and optional AI answer rewriting, plus source-text preservation.
---

Document OCR is local-only. Configuring a cloud answer provider or supplying its key does not authorize sending document page images to it, and there must be no cloud fallback when local OCR fails.

**Why:** the UI and README promise local processing. A previous coupling to the answer provider sent pages without a separate decision and replaced original evidence with an output-limited summary.

**How to apply:** preserve usable native text, OCR only pages lacking it, retain short native text alongside recognized content, and fail explicitly when local OCR is unavailable. Optional AI answer rewriting remains a separate operation with its own data-transfer implications.

Extraction-policy fixes must invalidate obsolete extracted-text caches, not just rebuild the retrieval index from those same caches.

**Why:** a cached cloud summary can keep omitting clauses even after the network path has been removed and the original PDF is still intact.

**How to apply:** upgrade uploaded-document extraction freshness and reconstruct cached text locally from the original source; do not invent or silently change dates or document identities.
