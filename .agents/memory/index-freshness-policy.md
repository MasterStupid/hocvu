---
name: Index freshness policy
description: Why built-in index freshness uses source fingerprints rather than manual version bumps.
---

Use automatic source fingerprints for built-in regulations and chunking logic, alongside the uploaded-document extraction version.

**Why:** Manual reindexing previously left students seeing outdated wording and citations after source updates. Manual version bumps have the same omission risk. Conservatively rebuilding after comment-only source edits is an accepted tradeoff for automatic detection.

**How to apply:** Keep server and CLI entry points on the same freshness check. If chunk generation acquires new source dependencies or settings, include them in freshness detection; do not require administrators to remember a reindex after code updates.
