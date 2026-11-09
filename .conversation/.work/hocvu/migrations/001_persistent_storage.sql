-- Development schema source. Replit Publish applies the dev -> prod schema diff.
-- Never execute DDL from application startup or a production build hook.
CREATE TABLE IF NOT EXISTS hv_turns (
    id BIGSERIAL PRIMARY KEY,
    session_id TEXT NOT NULL,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    intent TEXT,
    article_id TEXT,
    rid TEXT,
    context_question TEXT NOT NULL DEFAULT '',
    context_root TEXT NOT NULL DEFAULT '',
    refused INTEGER,
    references_json TEXT,
    card_json TEXT,
    confidence DOUBLE PRECISION,
    refusal_reason TEXT
);
CREATE INDEX IF NOT EXISTS hv_turns_session_idx ON hv_turns(session_id, id);
CREATE TABLE IF NOT EXISTS hv_closed_sessions (
    session_id TEXT PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS hv_session_owners (
    session_id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT to_char(clock_timestamp() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')
);
CREATE INDEX IF NOT EXISTS hv_session_owner_idx ON hv_session_owners(owner);
CREATE TABLE IF NOT EXISTS hv_document_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    revision BIGINT NOT NULL,
    manifest JSONB NOT NULL,
    objects JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS hv_storage_imports (
    source_digest TEXT PRIMARY KEY,
    backup_key TEXT NOT NULL,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
