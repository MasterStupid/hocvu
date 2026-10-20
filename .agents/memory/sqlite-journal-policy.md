---
name: SQLite journal policy
description: Why conversation-list optimization does not automatically enable WAL.
---

Preserve the configured journal mode when optimizing read-only conversation discovery. Treat enabling WAL as a separate storage decision.

**Why:** eliminating per-conversation SQL round trips does not require a journal-mode change. WAL improves reader/writer overlap, but changes persistent database behavior and backup requirements for live sidecar files. Enabling it inside the existing serialized initialization transaction is invalid.

**How to apply:** if WAL is deliberately adopted later, configure it outside the initialization transaction and verify concurrent startup, deletion, and backup/recovery. Keep write transactions short; never extend them around retrieval, LLM calls, or TTS to compensate for contention. The existing default SQLite connection timeout is already five seconds.
