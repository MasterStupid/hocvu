import sqlite3
import json
import time
from pathlib import Path

from .classifier import Classifier, Intent
from .scenarios import is_context_dependent


def validate_session_id(session_id: str) -> str:
    """Require an explicit ID while preserving every nonempty legacy name.

    Creation accepts arbitrary strings, including Unicode and punctuation.
    Never trim, normalize or interpret a name as a wildcard/SQL selector.
    """
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("Mã phiên không hợp lệ.")
    return session_id


class SessionClosedError(Exception):
    """A deleted ID is a permanent tombstone, never a new conversation."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        super().__init__("Hội thoại này đã bị xóa. Hãy bắt đầu hội thoại mới với mã phiên mới.")


class SessionAccessError(Exception):
    """Do not distinguish a foreign session from an unavailable legacy one."""


LEGACY_API_OWNER = "legacy-api"
SQLITE_BUSY_TIMEOUT_MS = 5000


class SessionStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=SQLITE_BUSY_TIMEOUT_MS / 1000)
        try:
            # This pragma is per connection, unlike the persistent WAL mode.
            conn.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
            return conn
        except BaseException:
            conn.close()
            raise

    @staticmethod
    def _enable_wal(conn):
        # PRAGMA journal_mode cannot change inside BEGIN IMMEDIATE. Two fresh
        # processes can also race the initial journal switch before migrations.
        deadline = time.monotonic() + SQLITE_BUSY_TIMEOUT_MS / 1000
        while True:
            try:
                mode = conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]
                if mode.lower() != "wal":
                    raise sqlite3.OperationalError("Không thể bật chế độ WAL cho cơ sở dữ liệu hội thoại.")
                return
            except sqlite3.OperationalError as exc:
                code = getattr(exc, "sqlite_errorcode", 0) & 0xFF
                remaining = deadline - time.monotonic()
                if code not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED) or remaining <= 0:
                    raise
                time.sleep(min(0.05, remaining))

    def _init_db(self):
        conn = self._connect()
        try:
            self._enable_wal(conn)
            # Serialize the additive migration across simultaneous engines.
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    question TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    intent TEXT,
                    article_id TEXT,
                    rid TEXT,
                    context_question TEXT NOT NULL DEFAULT '',
                    context_root TEXT NOT NULL DEFAULT ''
                )
            ''')
            columns = {row[1] for row in cursor.execute("PRAGMA table_info(turns)")}
            additions = {
                "context_question": "TEXT NOT NULL DEFAULT ''",
                "context_root": "TEXT NOT NULL DEFAULT ''",
                # NULL preserves the distinction between missing legacy state
                # and an explicitly non-refused, grounded response.
                "refused": "INTEGER",
                "references_json": "TEXT",
                "card_json": "TEXT",
                "confidence": "REAL",
                "refusal_reason": "TEXT",
            }
            for column, definition in additions.items():
                if column not in columns:
                    cursor.execute(f"ALTER TABLE turns ADD COLUMN {column} {definition}")
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS closed_sessions (
                    session_id TEXT PRIMARY KEY NOT NULL
                ) WITHOUT ROWID
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS session_owners (
                    session_id TEXT PRIMARY KEY NOT NULL,
                    owner TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                ) WITHOUT ROWID
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS session_owner_idx ON session_owners(owner)")
            cursor.execute("CREATE INDEX IF NOT EXISTS turns_session_idx ON turns(session_id, id)")
            conn.commit()
        finally:
            conn.close()

    def authorize(self, session_id: str, owner: str, *, create: bool = False):
        """Bind new IDs atomically; possession of a legacy ID is not ownership.

        Only a server-token API client may access unowned legacy records. A
        shared browser login is deliberately not sufficient authority.
        """
        validate_session_id(session_id)
        if not owner:
            raise SessionAccessError()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._authorize(conn, session_id, owner, create=create)
            conn.commit()
        finally:
            conn.close()

    def _authorize(self, conn, session_id: str, owner: str, *, create: bool = False):
        row = conn.execute(
            "SELECT owner FROM session_owners WHERE session_id = ?", (session_id,),
        ).fetchone()
        if row:
            if row[0] != owner:
                raise SessionAccessError()
        else:
            legacy = self._is_closed(conn, session_id) or conn.execute(
                "SELECT 1 FROM turns WHERE session_id = ? LIMIT 1", (session_id,),
            ).fetchone() is not None
            if legacy and owner != LEGACY_API_OWNER:
                raise SessionAccessError()
            if create:
                conn.execute(
                    "INSERT INTO session_owners(session_id, owner) VALUES (?, ?)",
                    (session_id, owner),
                )

    def list_conversations(self, owner: str) -> list[dict]:
        """Return only saved, open sessions in this authority's scope."""
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("BEGIN")
            # Join the first turn by primary key in the same read-only snapshot,
            # rather than issuing one title lookup per conversation.
            rows = conn.execute("""
                SELECT summary.session_id, first_turn.question AS title,
                       summary.turn_count, summary.updated_at
                FROM (
                    SELECT t.session_id, MIN(t.id) AS first_id, MAX(t.id) AS last_id,
                           COUNT(*) AS turn_count, o.updated_at
                    FROM turns t LEFT JOIN session_owners o ON o.session_id = t.session_id
                    WHERE (o.owner = ? OR (? = ? AND o.owner IS NULL))
                      AND NOT EXISTS (
                          SELECT 1 FROM closed_sessions c WHERE c.session_id = t.session_id
                      )
                    GROUP BY t.session_id
                ) summary
                JOIN turns first_turn ON first_turn.id = summary.first_id
                ORDER BY summary.last_id DESC
            """, (owner, owner, LEGACY_API_OWNER)).fetchall()
            return [{
                "session_id": row["session_id"], "title": row["title"][:120],
                "turn_count": row["turn_count"], "updated_at": row["updated_at"],
            } for row in rows]
        finally:
            conn.close()

    @staticmethod
    def _is_closed(conn, session_id: str) -> bool:
        return conn.execute(
            "SELECT 1 FROM closed_sessions WHERE session_id = ?", (session_id,),
        ).fetchone() is not None

    def is_closed(self, session_id: str, *, owner: str | None = None) -> bool:
        validate_session_id(session_id)
        conn = self._connect()
        try:
            if owner is not None:
                conn.execute("BEGIN")
                self._authorize(conn, session_id, owner)
            return self._is_closed(conn, session_id)
        finally:
            conn.close()

    def ensure_open(self, session_id: str):
        if self.is_closed(session_id):
            raise SessionClosedError(session_id)

    def add_turn(
        self, session_id: str, question: str, answer: str, intent: str,
        article_id: str, rid: str, *, context_question: str = "", context_root: str = "",
        response: dict | None = None,
    ):
        # Also defend callers other than HocVuEngine. Old ungrounded rows remain
        # readable, but new greetings/refusals must not become conversation state.
        if not question.strip() or intent != Intent.ACADEMIC_RULES.value or not article_id or not rid:
            return None
        if Classifier().classify(question) != Intent.ACADEMIC_RULES:
            return None
        if response is not None and response["refused"]:
            return None
        display_state = (
            int(response["refused"]),
            json.dumps(response["references"], ensure_ascii=False),
            json.dumps(response["card"], ensure_ascii=False),
            response["confidence"], response["refusal_reason"],
        ) if response is not None else (None, None, None, None, None)
        conn = self._connect()
        try:
            # The tombstone check and insert share a writer transaction. This
            # coordinates independent stores/processes, not just this engine.
            conn.execute("BEGIN IMMEDIATE")
            if self._is_closed(conn, session_id):
                raise SessionClosedError(session_id)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO turns (
                    session_id, question, answer, intent, article_id, rid,
                    context_question, context_root, refused, references_json,
                    card_json, confidence, refusal_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                session_id, question, answer, intent, article_id, rid,
                context_question or question,
                context_root or (question if not is_context_dependent(question) else ""),
                *display_state,
            ))
            conn.execute(
                "UPDATE session_owners SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE session_id = ?",
                (session_id,),
            )
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    def get_history(self, session_id: str, limit: int, *, owner: str | None = None) -> list[dict]:
        conn = self._connect()
        try:
            if owner is not None:
                # Authorization and data must share one snapshot, including
                # when an unknown ID is claimed concurrently by another owner.
                conn.execute("BEGIN")
                self._authorize(conn, session_id, owner)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM turns 
                WHERE session_id = ? 
                ORDER BY id DESC 
                LIMIT ?
            ''', (session_id, limit))
            rows = cursor.fetchall()
            history = []
            for row in reversed(rows):
                turn = dict(row)
                turn["refused"] = bool(turn["refused"]) if turn["refused"] in (0, 1) else None
                for column, public_name, expected_type in (
                    ("references_json", "references", list), ("card_json", "card", dict),
                ):
                    raw = turn.pop(column)
                    try:
                        value = json.loads(raw) if raw is not None else None
                    except (ValueError, TypeError):
                        value = None
                    turn[public_name] = value if isinstance(value, expected_type) else None
                history.append(turn)
            return history
        finally:
            conn.close()

    def delete_history(self, session_id: str) -> int:
        validate_session_id(session_id)
        conn = self._connect()
        try:
            # Equality and binding are intentional: no wildcard or all-session mode.
            with conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "INSERT OR IGNORE INTO closed_sessions (session_id) VALUES (?)",
                    (session_id,),
                )
                cursor = conn.execute("DELETE FROM turns WHERE session_id = ?", (session_id,))
            return cursor.rowcount
        finally:
            conn.close()

    def contextualize(self, session_id: str, question: str, limit: int = 8) -> tuple[str, str]:
        """Resolve against grounded turns, retaining the root across follow-ups.

        The root and a bounded tail of follow-ups prevent query growth. Raw
        questions remain intact in display history; legacy rows without resolved
        fields recover their root from an earlier independent grounded question.
        """
        if not is_context_dependent(question):
            return question, ""
        conn = self._connect()
        try:
            conn.row_factory = sqlite3.Row
            history = conn.execute('''
                SELECT question, context_question, context_root FROM turns
                WHERE session_id = ? AND intent = ?
                    AND COALESCE(refused, 0) = 0
                    AND TRIM(COALESCE(rid, '')) != ''
                    AND TRIM(COALESCE(article_id, '')) != ''
                ORDER BY id DESC LIMIT ?
            ''', (session_id, Intent.ACADEMIC_RULES.value, max(1, limit))).fetchall()
        finally:
            conn.close()
        classifier = Classifier()
        latest = None
        for turn in history:
            if classifier.classify(turn["question"]) != Intent.ACADEMIC_RULES:
                continue
            if latest is None:
                latest = turn
            root = turn["context_root"]
            if not root and not is_context_dependent(turn["question"]):
                root = turn["question"]
            if not root or classifier.classify(root) != Intent.ACADEMIC_RULES or is_context_dependent(root):
                continue
            prefix = f"{root} | "
            if latest["context_question"].startswith(prefix):
                tail = latest["context_question"][len(prefix):].split(" | ")
            else:
                tail = [latest["question"]] if latest["question"] != root else []
            # Always retain the root, even beyond the history window. Dedup and
            # cap only the tail so repeated ellipses do not grow the query.
            tail = list(dict.fromkeys([*tail, question]))
            return " | ".join([root, *tail[-max(1, limit - 1):]]), root
        return question, ""
