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

A calendar-valid date is not necessarily the correct effective date. Legacy recovery must use the administrator's reading of the original document, not a nearby valid day, the upload date, or today's date. Missing dates and valid future dates are not evidence of this legacy corruption.

**Why:** changing an effective date changes which historical questions the document may answer. The user explicitly requested selected, confirmed corrections rather than an automatic data migration.

**How to apply:** keep legacy invalid-date recovery separate from ordinary effective-date editing. Audit the actual target environment before claiming any old documents have been recovered.

Student-facing date explanations should use Vietnamese day/month/year (`DD/MM/YYYY`), while stored dates and retrieval comparisons remain ISO.

**Why:** the user identified an otherwise correct effectivity answer as a real display bug because it exposed an ISO date to Vietnamese students.

**How to apply:** format dates when composing explanatory text, including effectivity ranges and the lookup date. Do not rewrite source quotations or stored evidence snapshots merely to change display style.
