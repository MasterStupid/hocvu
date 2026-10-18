---
name: Wrapped subject safety
description: Tradeoff when inferring wrapped administrative subjects from extracted plain text.
---

Prefer leaving ambiguous capitalized continuations out of a subject over absorbing an unrelated body paragraph.

**Why:** Plain-text extraction does not reliably distinguish a soft wrap from a paragraph boundary. A contaminated title is reused in document previews and citations, so permissive joining can mislabel the document.

**How to apply:** Keep continuation inference conservative until real extraction fixtures supply reliable evidence for broader rules. Do not assume indentation alone proves a continuation.
