---
name: API origin protection
description: Why POST/DELETE API calls are origin-checked and how the Netlify proxy is allowed
---

POST/DELETE requests under /api/ must come from the same origin or an exact origin listed in HV_TRUSTED_ORIGINS. Cross-origin CORS stays disabled.

**Why:** Browser sign-in credentials and the Netlify proxy's injected API token are both sent automatically, so a token check alone lets other websites upload or delete regulations. Netlify forwards the browser's site Origin to a different backend host, so its exact site origin must be trusted on the backend.

**How to apply:** Never relax the check to "token present" or wildcard origins. When adding a separate frontend host, add its exact origin to HV_TRUSTED_ORIGINS on the API service.
