# HocVu AI on Replit

## Run

Use the **Start application** workflow (the Run button). It runs:

```sh
python manage.py serve --host 0.0.0.0 --port 5000
```

The existing FastAPI/Uvicorn server serves both the API and the static `ui/`
pages. No frontend build or separate service is needed.

## Access and configuration

- `HV_API_TOKEN` must be set in Replit Secrets before starting. Never put its
  value in source code or browser JavaScript.
- The Q&A page, its assets, suggestions and public regulation catalog require no
  password. Chat history remains scoped to each browser's `X-HocVu-Owner` key.
- `HV_BROWSER_AUTH=1` enables native browser sign-in for document management.
  Sign in with username `hocvu` and the password stored as `HV_API_TOKEN`.
  API clients can still send the `X-HocVu-Token` header. All `/api/documents`
  routes (including reads, upload, delete, date edits and reindex) stay protected.
  `/api/catalog` only exposes public title, regulation ID and version metadata.
  Browser-authenticated POST/DELETE requests must include a matching `Origin`;
  cross-site mutations are rejected and cross-origin CORS access is disabled.
- The UI and API share one origin. Leave `HV_TRUSTED_ORIGINS` empty for the
  normal single-server setup; keep the existing cross-site protection enabled.
  If the document management login prompt cannot appear in preview, open that
  page in a new tab. The Q&A page never requires that sign-in.
- `HV_SEMANTIC=0` uses the existing BM25 search without downloading embedding
  weights. Semantic retrieval is optional, not required to run.
- API documentation and the OpenAPI schema are disabled by default. Set
  `HV_API_DOCS=1` and restart only when you need `/docs`, `/redoc`, and
  `/openapi.json` for development. Keep it off on a published service.
- Questions sent to `/api/ask` are limited to 4000 characters; longer input
  receives HTTP 422 before retrieval is invoked.
- Optional Gemini/OpenAI rewriting remains off by default and requires its
  provider credentials and settings as documented in README.md.
- Tesseract is installed with Vietnamese language data for local OCR.

## Data and verification

The first startup generates the bundled **demonstration** regulations and index.
They are not official university regulations. Upload reviewed documents on
`/documents.html` before relying on the answers.

Uploaded files, indexes, audio, and SQLite sessions remain in the existing
git-ignored `data/` directory. Keep the original storage layout. This workspace
setup does not configure published-app persistent storage.

```sh
python -m unittest discover -s tests -v
python manage.py evaluate
```

Browser speech recognition requires microphone permission and a supported
browser (Chrome or Edge). Edge TTS requires access to Microsoft's service.
