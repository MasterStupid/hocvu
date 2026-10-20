---
name: Server test isolation
description: Non-obvious import-time storage bindings that can make integration tests affect live workspace data.
---

Server integration tests using a real engine must explicitly disable semantic model loading and isolate their resolved storage paths.

**Why:** changing an environment variable or the original settings module after import does not update path aliases already imported elsewhere, or default argument values captured earlier. A seemingly isolated authentication test can consequently write into the working session store or download model weights.

**How to apply:** pass temporary storage paths where supported and isolate remaining imported aliases, including directory-creation paths. Reset the lazy engine for each test and restore it afterward. Use a fail-fast model-constructor guard for tests that should stay offline; keep synthetic credentials independent of the hosting configuration.
