---
name: Hosting and access decision
description: User's chosen hosting target (Replit only) and who may use which pages
---

The user decided (2026-10-18) to drop Netlify + Render and host HocVu AI only on Replit.
Access model chosen by the user: the Q&A chat is public; only document management (documents page and upload/delete/reindex/text APIs) requires the password.

**Why:** the user asked for it; one Replit server already serves UI + API, so the proxy, split token, and trusted-origin setup add complexity. Students must be able to ask without a shared password, while the regulation corpus stays protected.

**How to apply:** a published Replit app's disk resets on every publish, so uploaded documents must go to App Storage and chat sessions to the Replit PostgreSQL database; rebuild the search index from stored documents at startup. Prefer a Reserved VM deployment (index and rate limiter live in memory; Autoscale instances would diverge after uploads). Keep cross-site protection on mutating routes. The user asked to do this migration only after the document-heading work finished, since both touch the document-processing code.
