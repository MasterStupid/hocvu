---
name: API origin protection
description: Why browser mutations stay origin-checked even with a single-server hosting setup
---

POST/DELETE requests under /api/ must come from the same origin or an exact origin listed in HV_TRUSTED_ORIGINS. Cross-origin CORS stays disabled.

**Why:** browsers send sign-in credentials automatically, so checking only a password or token can still allow a different website to trigger document uploads or deletion. Serving the UI and API together removes deployment complexity, not this security requirement.

**How to apply:** never relax the check to "token present" or wildcard origins. The bundled frontend uses the same origin; the advanced trusted-origin allowlist should normally be empty. A new cross-origin frontend requires an explicit hosting decision and an exact allowlist entry.
