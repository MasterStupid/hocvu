---
name: Voice playback cancellation
description: Shared browser playback ownership and why stopping media alone does not prevent old speech from restarting.
---

All browser voice paths share one cancellation lifecycle. Invalidate playback ownership before stopping MP3 playback, cancelling browser synthesis and clearing voice-retry timers.

**Why:** HTML audio errors and play-promise failures can arrive after cancellation and incorrectly start browser fallback for an old answer. Cancelling only Web Speech leaves server-generated MP3 playback running.

**How to apply:** new voice paths must stop on Live/TTS disable, a new question, replacement speech or a new conversation. Guard asynchronous callbacks before any state mutation, including clearing timer handles: an old callback must not clear a newer retry handle or mark a newer utterance finished. The error event and rejected play promise must not both start fallback.
