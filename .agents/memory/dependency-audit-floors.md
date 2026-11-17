---
name: Dependency audit floors
description: Why installed package upgrades alone do not resolve this project's manifest vulnerability findings.
---

Treat allowed minimum versions as part of the dependency security contract, not just the installed environment.

**Why:** the dependency scanner reported vulnerable lower-bound releases even though the installed packages were already patched. Raising the manifest minimums cleared the findings without changing the installed environment.

**How to apply:** inspect both declared requirements and installed versions before installing upgrades. Keep hosted and full dependency security minimums aligned, retain optional semantic retrieval, and rerun the dependency audit after editing requirements.

Repeat the audit after raising transitive security floors, including for optional dependencies.

**Why:** fixing an optional model dependency can change its resolved HTTP stack and expose vulnerabilities that were absent from the initial report.

**How to apply:** resolve both the full and hosted requirements without installing optional model runtimes, then keep scanning until newly introduced dependency findings are addressed.

Keep raw dependency scan results out of persistent notebook variables and return only a compact summary.

**Why:** affected-version histories can make the raw result exceed the notebook memory limit, resetting its state even when the scan succeeds.

**How to apply:** scope the raw result inside an async function and return severity counts plus package, fix, and file information; avoid logging complete affected-version arrays.
