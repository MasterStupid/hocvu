---
name: Index freshness policy
description: Why index freshness covers source code and the exact uploaded-document manifest snapshot.
---

Use automatic source fingerprints for built-in regulations and chunking logic, alongside the uploaded-document extraction version.

**Why:** Manual reindexing previously left students seeing outdated wording and citations after source updates. Manual version bumps have the same omission risk. Conservatively rebuilding after comment-only source edits is an accepted tradeoff for automatic detection.

**How to apply:** Keep server and CLI entry points on the same freshness check. If chunk generation acquires new source dependencies or settings, include them in freshness detection; do not require administrators to remember a reindex after code updates.

Freshness must also describe the uploaded-document snapshot actually represented by the index, not merely the current code or whichever manifest is present when saving finishes.

**Why:** a document mutation can commit before indexing and survive an interrupted build. Reading a newer manifest after building older chunks can falsely mark missing documents as indexed indefinitely.

**How to apply:** hash the same captured manifest entries used for chunk construction, including upgrades made to that snapshot. Conservatively include metadata rather than guessing which external edits matter; ignore JSON formatting differences, not document order. A later manifest change must remain detectable on the next load.
