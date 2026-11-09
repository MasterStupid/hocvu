---
name: Conversation ownership boundary
description: Why shared document login and historical session IDs are not proof of chat ownership.
---

Conversation discovery and operations must be scoped to a separate browser-profile capability, not the shared browser password or possession of a session ID. Explicit server-token clients may retain their legacy/API-only authority but must not inherit browser-owned conversations.

**Why:** the chat has no individual accounts; a shared document password identifies no individual student. Legacy records did not record ownership, so automatically claiming them from a known ID could disclose someone else's history.

**How to apply:** do not auto-assign unowned legacy records to a browser, even during migration. Clearly explain unavailable legacy history without deleting it. Treat clearing browser storage or changing origin/device as losing capability access, not as permission to re-claim IDs. Any recovery or cross-device transfer needs a separate, verifiable authorization mechanism. Preserve ownership and closure markers alongside history in storage migrations.
