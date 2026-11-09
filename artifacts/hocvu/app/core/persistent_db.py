"""PostgreSQL connections and the SQL dialect boundary for conversation storage."""
from __future__ import annotations

import os
import re


class StorageUnavailable(RuntimeError):
    pass


def connect_database():
    """Credentials stay in the process; never return or log a connection string."""
    import psycopg
    if not os.environ.get("DATABASE_URL"):
        raise StorageUnavailable("Chưa cấu hình PostgreSQL. Không chuyển sang lưu cục bộ.")
    try:
        return psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=10)
    except psycopg.Error:
        raise StorageUnavailable("Không kết nối được PostgreSQL. Không chuyển sang lưu cục bộ.") from None


class DatabaseRow(dict):
    """Support the existing store's positional authorization and named results."""
    def __getitem__(self, key):
        return tuple(self.values())[key] if isinstance(key, int) else super().__getitem__(key)


def row_factory(cursor):
    names = [column.name for column in cursor.description or ()]
    return lambda values: DatabaseRow(zip(names, values))


def conversation_sql(sql: str) -> str:
    """Translate only our static SQL, never interpolating caller values."""
    if sql.strip() in {"BEGIN", "BEGIN IMMEDIATE"}:
        # psycopg starts the transaction itself before this first statement.
        return "SELECT 1"
    sql = sql.replace(
        "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')",
        """to_char(clock_timestamp() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')""",
    )
    ignore = "INSERT OR IGNORE INTO closed_sessions" in sql
    sql = sql.replace("INSERT OR IGNORE", "INSERT")
    for table in ("turns", "session_owners", "closed_sessions"):
        sql = re.sub(rf"\b{table}\b", f"hv_{table}", sql)
    sql = sql.replace("?", "%s")
    if ignore:
        sql += " ON CONFLICT DO NOTHING"
    return sql


class ConversationCursor:
    def __init__(self, connection):
        self.connection = connection
        self.cursor = connection.raw.cursor(row_factory=row_factory)
        self.lastrowid = None

    def execute(self, sql, params=()):
        # Lock before reading/creating ownership, testing a tombstone, or saving
        # a turn. All instances use the same per-session transaction lock.
        if params and re.search(
            r"WHERE\s+session_id\s*=|closed_sessions\s*\(session_id\)|INSERT\s+INTO\s+turns\s*\(",
            sql, re.I,
        ):
            self.connection.lock_session(str(params[0]))
        returning = bool(re.search(r"INSERT\s+INTO\s+turns\s*\(", sql, re.I))
        translated = conversation_sql(sql)
        if returning:
            translated += " RETURNING id"
        self.cursor.execute(translated, params)
        if returning:
            self.lastrowid = self.cursor.fetchone()[0]
        return self

    @property
    def rowcount(self):
        return self.cursor.rowcount

    def fetchone(self):
        return self.cursor.fetchone()

    def fetchall(self):
        return self.cursor.fetchall()


class ConversationConnection:
    """Small adapter so both stores share evidence, context and ownership rules."""
    row_factory = None

    def __init__(self, raw):
        self.raw = raw
        self._locked = set()

    def lock_session(self, session_id):
        if session_id not in self._locked:
            self.raw.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                ("hocvu-history:" + session_id,),
            )
            self._locked.add(session_id)

    def cursor(self):
        return ConversationCursor(self)

    def execute(self, sql, params=()):
        return self.cursor().execute(sql, params)

    def commit(self):
        self.raw.commit()
        self._locked.clear()

    def close(self):
        self.raw.close()

    def __enter__(self):
        return self

    def __exit__(self, kind, value, traceback):
        if kind is None:
            self.commit()
        else:
            self.raw.rollback()
            self._locked.clear()
