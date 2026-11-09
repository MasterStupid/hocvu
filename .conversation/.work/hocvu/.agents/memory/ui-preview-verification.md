---
name: UI preview verification
description: How to visually check the Q&A dashboard when the main workflow cannot start or history needs seeding.
---

When App Storage is unreachable the "Start application" workflow fails at startup (StorageUnavailable); this is an environment problem, not a UI bug. For UI-only checks, run a throwaway server with `HV_STORAGE_BACKEND=local HV_SEMANTIC=0 HV_DATA_DIR=/tmp/<dir>` so real storage and `data/` are untouched, then stop it.

**Why:** local mode against the default data dir could mix a disposable cache with the source-of-truth policy; a temp dir avoids that.

**How to apply:** the screenshot browser caches `/`; request `/index.html?<unique>` instead. Non-whitelisted files under `ui/` return 401, so seeding localStorage for a screenshot needs a temporary edit to an already-served script — always revert it and its cache-buster afterwards.
