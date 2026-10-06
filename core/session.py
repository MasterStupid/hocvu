import sqlite3
from pathlib import Path

class SessionStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    question TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    intent TEXT,
                    article_id TEXT,
                    rid TEXT
                )
            ''')
            conn.commit()
        finally:
            conn.close()

    def add_turn(self, session_id: str, question: str, answer: str, intent: str, article_id: str, rid: str):
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO turns (session_id, question, answer, intent, article_id, rid)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (session_id, question, answer, intent, article_id, rid))
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
            return [dict(row) for row in reversed(rows)]
        finally:
            conn.close()

    def contextualize(self, session_id: str, question: str) -> tuple[str, str]:
        history = self.get_history(session_id, 3)
        if not history:
            return question, ""
            
        context_str = " | ".join([t['question'] for t in history])
        expanded = f"{context_str} | {question}"
        return expanded, context_str
