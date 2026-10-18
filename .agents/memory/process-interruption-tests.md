---
name: Process-interruption tests
description: Multiprocessing pitfalls when deterministically testing abrupt writer interruption.
---

Keep parent references to every synchronization object until spawned workers have exited. After forcibly terminating a worker, do not signal Events it may have been waiting on.

**Why:** Spawned workers can fail while reconstructing semaphores if the parent garbage-collects ignored Event references. Termination during an Event wait can also leave its internal condition lock held, so signaling that Event during cleanup can hang the entire test suite.

**How to apply:** Retain all worker Events through cleanup, even when the caller ignores a returned value. Only signal a release Event for a worker that is still alive; join an already terminated worker without touching its synchronization objects.
