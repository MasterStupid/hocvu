---
name: Server voice fallback
description: The hosted Edge read-aloud provider fails intermittently from this host; how playback must degrade.
---

The free Edge read-aloud endpoint intermittently returns no audio for new (uncached) Vietnamese text from this host, then succeeds on a second or third attempt. It is not related to the text, voice or rate.

**Why:** the "Nghe" button returned a 500 in the user's student-experience test; for a voice-assistant thesis, reading aloud must not depend on one flaky provider.

**How to apply:** retry briefly on the server and report a distinct "temporarily unavailable" status rather than a generic 500 with provider details. In the browser, fall back once per playback to the built-in Vietnamese voice and tell the listener which voice is in use; if the browser has no Vietnamese voice, say so instead of reading with a foreign voice. The fallback shares the single cancellation lifecycle (see voice-playback-cancellation.md). A slow first "Nghe" (several seconds) is the retry at work, not a hang.
