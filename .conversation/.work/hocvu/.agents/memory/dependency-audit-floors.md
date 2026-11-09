---
name: Dependency audit floors
description: Why installed package upgrades alone do not resolve this project's manifest vulnerability findings.
---

Treat allowed minimum versions as part of the dependency security contract, not just the installed environment.

**Why:** the dependency scanner reported vulnerable lower-bound releases even though the installed packages were already patched. Raising the manifest minimums cleared the findings without changing the installed environment.

**How to apply:** inspect both declared requirements and installed versions before installing upgrades. Keep hosted and full dependency security minimums aligned, retain optional semantic retrieval, and rerun the dependency audit after editing requirements.
