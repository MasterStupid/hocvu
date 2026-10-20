---
name: Hosting and access decision
description: User's chosen hosting target (Replit only) and who may use which pages
---

The user chose Replit-only hosting on 2026-10-18, and reiterated on 2026-10-20 that legacy separate-frontend deployment connections, configuration and scripts should be removed rather than maintained.
Access model chosen by the user: the Q&A chat is public; only document management (documents page and upload/delete/reindex/text APIs) requires the password.

**Why:** the user asked for it; one Replit server already serves UI + API, so a deployment proxy and split token add complexity. Do not recreate a separate frontend host or its build integration unless the user explicitly changes this hosting decision. Students must be able to ask without a shared password, while the regulation corpus stays protected.

Removing the chat password must not mean globally disabling authentication. Public chat uses browser-scoped conversation ownership; that capability is never document-administration authority. Keep sensitive management reads protected as well as writes, and expose only the minimum public catalog metadata needed by chat.

**How to apply:** a published Replit app's disk resets on every publish, so uploaded documents must go to App Storage and chat sessions to the Replit PostgreSQL database; rebuild the search index from stored documents at startup. Prefer a Reserved VM deployment (index and rate limiter live in memory; Autoscale instances would diverge after uploads). Keep cross-site protection on mutating routes. The user asked to do this migration only after the document-heading work finished, since both touch the document-processing code.
