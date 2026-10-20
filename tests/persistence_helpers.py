import os
from pathlib import Path
import unittest
import uuid
from unittest.mock import patch

from core import persistent_db, persistent_documents, postgres_session, storage_transfer


class MemoryObjects:
    """Only the App Storage transport is faked; integration SQL is real."""
    def __init__(self):
        self.items = {}
        self.fail = False

    def exists(self, key):
        return key in self.items

    def upload_from_bytes(self, key, data):
        if self.fail:
            raise OSError("storage unavailable")
        self.items[key] = data

    def upload_from_filename(self, key, path):
        self.upload_from_bytes(key, Path(path).read_bytes())

    def download_as_bytes(self, key):
        return self.items[key]


class PostgresCase(unittest.TestCase):
    def setUp(self):
        if os.environ.get("REPLIT_DEPLOYMENT") == "1":
            self.skipTest("Never create test schemas from a published process")
        if os.environ.get("HV_TEST_POSTGRES") != "1":
            self.skipTest("Set HV_TEST_POSTGRES=1 to run isolated PostgreSQL integration tests")
        from psycopg import sql
        real_connect = persistent_db.connect_database
        name = "hv_test_" + uuid.uuid4().hex
        with real_connect() as connection:
            connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(name)))

        def cleanup():
            with real_connect() as connection:
                connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(name)))
        self.addCleanup(cleanup)

        def connect():
            connection = real_connect()
            connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(name)))
            connection.commit()
            return connection
        self.connect = connect
        with connect() as connection:
            connection.execute((Path(__file__).resolve().parents[1] / "migrations/001_persistent_storage.sql").read_text())
        for module in (persistent_db, persistent_documents, postgres_session, storage_transfer):
            self.enterContext(patch.object(module, "connect_database", connect))


QUESTION = "Điều kiện bảo lưu kết quả học tập là gì?"
RESPONSE = {
    "refused": False, "references": [{"rid": "UPL-TEST", "aid": "Điều 1", "excerpt": "Nguồn gốc"}],
    "card": {"summary": "Kết quả nguyên bản"}, "confidence": 0.8, "refusal_reason": "",
}


def add_turn(store, session_id, *, question=QUESTION, response=RESPONSE):
    return store.add_turn(
        session_id, question, "Câu trả lời có căn cứ.", "academic_rules", "Điều 1", "UPL-TEST",
        context_question=question, context_root=QUESTION, response=response,
    )
