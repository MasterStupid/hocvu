---
name: Netlify build configuration
description: Why legacy Netlify proxy setup uses an in-memory pre-build hook rather than rendering secrets into configuration files.
---

Keep legacy Netlify proxy injection in the pre-build lifecycle; the ordinary build command only validates its inputs. Do not render private proxy headers into tracked configuration or published frontend assets.

**Why:** Netlify has already loaded its configuration before executing a build command. Rewriting its source file at that point is not a reliable configuration mechanism, leaves credentials in the working tree and makes repeat builds depend on restoring placeholders.

**How to apply:** preserve the local pre-build hook when changing the build scripts. Repeated execution must replace the existing API rule rather than append duplicates, while retaining unrelated redirects. Test with synthetic credentials; do not use or print workspace secrets.
