import sqlite3
import json
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


class SessionStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        try:
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
            conn.commit()
        finally:
            conn.close()

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
        conn = sqlite3.connect(self.db_path)
        try:
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
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    def get_history(self, session_id: str, limit: int) -> list[dict]:
        conn = sqlite3.connect(self.db_path)
        try:
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
        conn = sqlite3.connect(self.db_path)
        try:
            # Equality and binding are intentional: no wildcard or all-session mode.
            with conn:
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
        conn = sqlite3.connect(self.db_path)
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
