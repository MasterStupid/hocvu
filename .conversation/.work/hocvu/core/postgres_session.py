"""Persistent history without duplicating the SQLite store's grounding policy."""
from .persistent_db import ConversationConnection, StorageUnavailable, connect_database
from .session import SessionStore


class PostgresSessionStore(SessionStore):
    def __init__(self):
        # Validate schema, never create/alter production tables at startup.
        with connect_database() as connection:
            try:
                connection.execute("SELECT id, references_json, context_root FROM hv_turns LIMIT 0")
                connection.execute("SELECT session_id FROM hv_closed_sessions LIMIT 0")
                connection.execute("SELECT owner, updated_at FROM hv_session_owners LIMIT 0")
            except Exception:
                raise StorageUnavailable(
                    "Thiếu bảng PostgreSQL. Áp dụng schema development và publish; không dùng SQLite thay thế."
                ) from None

    def _connect(self):
        return ConversationConnection(connect_database())
