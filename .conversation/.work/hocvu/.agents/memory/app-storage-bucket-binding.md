---
name: App Storage bucket binding
description: Why startup fails with StorageUnavailable and how the app picks its bucket.
---

The app reads its bucket from the HV_STORAGE_BUCKET_ID env var, not from `.replit` `[objectStorage] defaultBucketID`. The platform can switch the default bucket; the old one then returns Forbidden and startup fails with "Chưa truy cập được App Storage".

**Why:** this happened once — env var still pointed to the previous bucket after the platform changed the default.

**How to apply:** on that startup error, probe both IDs with `replit.object_storage.Client(bucket_id=...).exists(...)` and point HV_STORAGE_BUCKET_ID at the accessible default bucket; never fall back to disk storage.
