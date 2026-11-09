---
name: Vietnamese PDF fixture fonts
description: Avoid incomplete Vietnamese text when generating portable PDF fixtures.
---

Do not assume standard PDF fonts or a bundled CJK font contain all Vietnamese characters. Generate Vietnamese PDFs with Unicode font fallback rather than depending on fonts installed on the host.

**Why:** Both base fonts and the bundled CJK fallback lacked Vietnamese glyphs during fixture generation. Missing glyphs can make an extraction test exercise corrupted text instead of the intended subject.

**How to apply:** For new Vietnamese PDF fixtures, use a renderer with Unicode fallback and verify the exact extracted accented text. Keep generated binaries temporary rather than committing font-heavy PDFs.
