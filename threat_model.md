# Threat Model

## Project Overview

HocVu AI is a Vietnamese academic-regulation Q&A assistant (RAG + voice) for ĐH Hải Phòng. It is a Python FastAPI/Uvicorn app served by `python manage.py serve`, serving both the JSON API and the static `ui/` pages from a single origin. Retrieval uses BM25 (optionally semantic embeddings). Optional answer rewriting can call OpenAI or Gemini. Text-to-speech uses Microsoft Edge TTS. Persistence is either local (SQLite/WAL + local files) or Replit (PostgreSQL metadata/history + App Storage blobs). Users: anonymous students (public Q&A) and document-management administrators (upload/delete/reindex/backup).

## Assets

- **Regulation documents and extracted text** — admin-uploaded source of truth for answers; tampering degrades answer integrity.
- **Conversation history** — per-browser chat history (questions/answers); private to each browser owner key. Backups contain all history and are private.
- **Application secrets** — `HV_API_TOKEN` (document/API password and admin Basic password), optional OpenAI/Gemini keys, PostgreSQL connection string. Must never reach client code or logs.
- **Storage/backup artifacts** — private ZIP backups containing chat history.

## Trust Boundaries

- **Browser ↔ API** — all client requests are untrusted. Chat endpoints are public but scoped per-browser owner; document/admin endpoints require the API token or admin Basic auth.
- **API ↔ SQLite/PostgreSQL** — parameterized queries throughout `core/session.py`.
- **API ↔ External LLM/TTS** — outbound calls use operator-configured base URLs (not user-supplied), so no user-driven SSRF.
- **Public (chat) ↔ Authenticated (documents/admin)** — enforced server-side in `server/app.py` middleware via an explicit `PUBLIC_CHAT_API`/`PUBLIC_CHAT_PAGES` allowlist; everything else under `/api/` requires auth.
- **Internet ↔ App** — Replit terminates TLS; `proxy_headers=False` with an explicit `HV_TRUSTED_PROXIES` policy for client-IP derivation.

## Scan Anchors

- Production entry points: `server/app.py` (all routes + auth/rate-limit middleware), `server/security.py` (rate limiter, proxy trust), `manage.py serve`.
- Highest-risk areas: auth/CSRF middleware (`rate_limit_and_auth_middleware`), `conversation_owner`/`valid_browser_credentials`, document upload/delete/date/reindex handlers, `/api/audio/{filename}` and `/api/admin/storage/backups/{filename}` (path traversal surfaces), `core/documents.py` (file handling), `core/session.py` (ownership/IDOR, SQL), `core/llm.py` (outbound HTTP), `core/storage_transfer.py` (backup/import).
- Public surfaces: `/`, static UI, `/api/health`, `/api/catalog`, `/api/suggestions`, `/api/ask`, `/api/history*`, `/api/conversations`, `/api/tts`, `/api/audio/*`.
- Authenticated surfaces: `/api/documents*`, `/api/admin/*`.
- Dev-only/ignore unless proven reachable: bundled demo regulations/index, `tests/`, `scripts/benchmark_searcher.py`, local SQLite mode (published apps refuse local mode).

## Threat Categories

### Spoofing / Improper Authentication

Chat ownership is a client-generated 64-hex key (`crypto.randomUUID()` x2) stored only as a SHA-256 digest server-side; invalid owner headers are rejected (no silent fallback to token authority). Document/admin routes require `HV_API_TOKEN` (constant-time compare) or optional Basic auth (`hocvu` + token). The server must never trust a client-supplied owner in query/body. Guarantee: every `/api/` route except the explicit public chat allowlist requires valid credentials; the server establishes the subject before acting.

### Tampering / CSRF

Document mutations use ambient Basic credentials, so the middleware additionally rejects cross-site writes via `Sec-Fetch-Site: cross-site`, `Origin` allowlist, and a browser-authenticated-but-missing-Origin rule. Answer content is computed server-side from indexed documents. Guarantee: state-changing `/api/` requests must pass same-origin checks.

### Information Disclosure

`/api/catalog` exposes only `rid`/`title`/`version`, not filenames or admin fields. Conversation reads/lists are owner-scoped in shared DB snapshots to prevent IDOR. Backup downloads require a strict filename regex, reject symlinks, and only serve from the backups cache dir. Audio serving validates the resolved path stays within the audio root, forbids separators, and requires `.mp3`. API docs/OpenAPI are disabled by default. Guarantee: no cross-owner history access; secrets never sent to the client.

### Elevation of Privilege

No SQL string concatenation (parameterized throughout), no `eval`/`exec`/`subprocess`/`pickle` on untrusted input (NumPy loads use `allow_pickle=False`). Document `item_id`s are resolved against the manifest before any filesystem path is built, preventing path traversal. Guarantee: object-level authorization precedes data access, and privileged actions sit behind the authenticated boundary.

### Denial of Service

Per-client sliding-window rate limiting on protected/non-public routes, bounded request bodies (25 MB/file, 50 MB/batch, bounded batch counts and multipart part sizes), 4000-char question cap, and outbound LLM timeouts. Guarantee: unauthenticated input is size- and rate-bounded.
