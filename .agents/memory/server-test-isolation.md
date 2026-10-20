---
name: Server test isolation
description: Import-time storage bindings and execution constraints for safe server regression tests.
---

Server integration tests using a real engine must explicitly disable semantic model loading and isolate their resolved storage paths.

**Why:** changing an environment variable or the original settings module after import does not update path aliases already imported elsewhere, or default argument values captured earlier. A seemingly isolated authentication test can consequently write into the working session store or download model weights.

**How to apply:** pass temporary storage paths where supported and isolate remaining imported aliases, including directory-creation paths. Reset the lazy engine for each test and restore it afterward. Use a fail-fast model-constructor guard for tests that should stay offline; keep synthetic credentials independent of the hosting configuration.

Run long subprocess-heavy regression suites as background shell tasks.

**Why:** foreground runs in this environment have repeatedly exhausted the shell-call time budget, while the identical suite completed normally in a background task. A partial log ending at a subprocess test is not by itself evidence of a failed assertion or deadlock.

**How to apply:** use the normal module entry point, wait for the completion notification, and read the final test summary. Check that a timed-out foreground process is gone before starting a replacement; never report a partial pass count as a complete run.
