---
name: Document date integrity
description: Why invalid OCR dates require explicit correction rather than an automatic effective-date fallback.
---

Reject an impossible automatically detected calendar date with an actionable upload error. A valid date entered by the administrator takes precedence over OCR.

**Why:** the effective date controls whether the regulation can be retrieved. Guessing a replacement can make it valid at the wrong time; accepting an impossible date creates a misleading ready document that date-filtered searches cannot see.

**How to apply:** only use the stable upload-day fallback when no date was detected or entered, not when a detected date is invalid. Keep search filtering fail-closed for malformed metadata, and require explicit correction before changing dates on existing documents.

Correcting an existing document's date must not require deleting or re-uploading it; preserve its identity and original file.

**Why:** the user requested in-place date corrections with the same document code and file.

**How to apply:** require an explicit, valid replacement date and do not treat a failed index update as a successful correction.
