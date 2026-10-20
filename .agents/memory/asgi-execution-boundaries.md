---
name: ASGI execution boundaries
description: Why upload admission and document mutation scheduling must protect both responsiveness and memory.
---

Keep expensive synchronous engine work, including lazy initialization, off the ASGI event loop. Serialize document mutations locally, but do not put ordinary questions or health checks behind that writer gate.

**Why:** long OCR, model inference and synchronous network waits must not freeze unrelated requests. Offloading also introduces concurrent writers into the manifest's read/modify/write cycle.

Acquire the document writer gate before reading a bounded upload into bytes, not just before indexing it.

**Why:** a per-file read limit alone still allows many queued uploads to retain full-size byte buffers simultaneously. Waiting uploads should remain spooled rather than each retaining another 25 MB buffer.

**How to apply:** include new document-changing endpoints in the same admission boundary while keeping read-only work independent. This gate only coordinates one server process; it does not replace cross-process storage locking.
