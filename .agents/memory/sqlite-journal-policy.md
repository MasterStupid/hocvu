---
name: SQLite journal policy
description: User-requested WAL adoption, safe initialization boundaries, and live backup requirements.
---

The user explicitly requested WAL for the SQLite conversation store. Enable it outside the initialization/migration transaction, keeping write transactions short and the five-second busy timeout on every connection.

**Why:** the earlier list-query optimization deliberately preserved journal mode because removing N+1 did not require changing storage behavior. The user's subsequent request adopts WAL to improve reader/writer overlap. A journal-mode switch inside an active transaction is invalid; fresh concurrent initializers may also contend while switching modes.

**How to apply:** keep WAL configuration before migration begins, bound retries to the lock timeout, and fail explicitly instead of silently falling back to another mode. Verify concurrent startup and deletion without dropping ownership or permanent closure markers. Never extend a write transaction around retrieval, LLM calls, or TTS.

Use SQLite's backup API for live backups; do not copy only the main database file or delete live journal sidecars.

**Why:** recent committed history and closure markers may still be in the WAL, so a main-file-only copy can lose data even when SQL commits succeeded.

**How to apply:** preserve SQLite snapshot semantics during online backup; stop all database users and close connections cleanly before filesystem-only backups.

An open but idle connection does not necessarily retain a WAL generation; an actual read snapshot controls checkpoint retention.

**Why:** SQLite can defer attaching a connection to the database/WAL, so concurrent connections closing may checkpoint and remove the WAL despite an idle connection still existing.

**How to apply:** when verifying live-WAL backup behavior, hold a real read snapshot during concurrent commits. End that older snapshot before taking a backup intended to include the latest commits.
