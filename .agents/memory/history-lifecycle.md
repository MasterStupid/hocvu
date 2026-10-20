---
name: Conversation history lifecycle
description: Why starting a new conversation and permanently deleting saved history must remain separate.
---

Starting a new conversation must not implicitly delete its predecessor. Permanent deletion is a separate, explicitly confirmed action limited to one chosen session.

**Why:** the user explicitly requested this distinction; opening a fresh conversation is not consent to destroy saved data.

**How to apply:** preserve this distinction when adding conversation lists, switching or retention features. Do not equate clearing the visible chat with deleting its persisted records.

Deletion must accept every nonempty legacy session name, including Unicode, spaces and punctuation, not just browser-generated UUIDs. Do not trim or normalize names.

**Why:** API callers historically supplied arbitrary strings; imposing new character or length restrictions only on deletion strands histories that can still be created and read.

**How to apply:** retain exact identifier matching and explicit validation at destructive boundaries; never add a missing-ID fallback or an all-session mode.

Treat a deleted session ID as permanently closed, rather than a reusable empty
conversation. Keep the closure marker even when the ID had no saved turns.

**Why:** a delayed request can outlive deletion by an arbitrary amount of time.
Reopening or expiring the marker would allow another tab/client to recreate
deleted history. Permanent closure avoids relying on synchronized clocks or on
every caller supplying a new generation token.

**How to apply:** clients must use a fresh ID after deletion, never retry the old
question automatically under a new ID. Any future retention, backup/restore or
storage migration must preserve closure markers along with history.
