"""WAL startup, contention and online backups use isolated SQLite databases."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from core.session import SessionClosedError, SessionStore, SQLITE_BUSY_TIMEOUT_MS


def add_turn(store, session_id):
    return store.add_turn(
        session_id, "Điều kiện bảo lưu?", "Căn cứ mẫu", "academic_rules", "Điều 5", "synthetic",
    )


class SessionWalTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.path = self.root / "sessions.db"
        self.store = SessionStore(self.path)

    def test_wal_is_persistent_and_is_enabled_before_migration_transaction(self):
        connect, statements = sqlite3.connect, []

        def traced(*args, **kwargs):
            conn = connect(*args, **kwargs)
            conn.set_trace_callback(statements.append)
            return conn

        with patch("core.session.sqlite3.connect", side_effect=traced):
            SessionStore(self.path)
        journal = next(i for i, sql in enumerate(statements) if "journal_mode=WAL" in sql)
        migration = next(i for i, sql in enumerate(statements) if "BEGIN IMMEDIATE" in sql)
        self.assertLess(journal, migration)
        with closing(connect(self.path)) as conn:
            self.assertEqual(conn.execute("PRAGMA journal_mode").fetchone()[0], "wal")
        # Existing DELETE-mode stores are migrated without losing history.
        add_turn(self.store, "legacy")
        with closing(connect(self.path)) as conn:
            self.assertEqual(conn.execute("PRAGMA journal_mode=DELETE").fetchone()[0], "delete")
        reopened = SessionStore(self.path)
        self.assertEqual(len(reopened.get_history("legacy", 10)), 1)
        with closing(connect(self.path)) as conn:
            self.assertEqual(conn.execute("PRAGMA journal_mode").fetchone()[0], "wal")

    def test_every_store_connection_explicitly_sets_the_busy_timeout(self):
        connect, observations = sqlite3.connect, []

        def traced(*args, **kwargs):
            conn = connect(*args, **kwargs)
            conn.set_trace_callback(lambda sql: observations.append(sql) if "busy_timeout=" in sql else None)
            return conn

        with patch("core.session.sqlite3.connect", side_effect=traced):
            store = SessionStore(self.path)
            store.authorize("owned", "synthetic-owner", create=True)
            add_turn(store, "owned")
            store.get_history("owned", 10)
            store.list_conversations("synthetic-owner")
            store.is_closed("owned")
            store.ensure_open("owned")
            store.contextualize("owned", "Còn điều kiện nào khác?")
            store.delete_history("owned")
        self.assertEqual(len(observations), 9)
        self.assertTrue(all(sql == f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}" for sql in observations))
        with closing(self.store._connect()) as conn:
            self.assertEqual(conn.execute("PRAGMA busy_timeout").fetchone()[0], 5000)

    def test_writer_commits_without_waiting_for_a_read_snapshot(self):
        add_turn(self.store, "selected")
        with closing(self.store._connect()) as reader:
            reader.execute("BEGIN")
            self.assertEqual(reader.execute("SELECT COUNT(*) FROM turns").fetchone()[0], 1)
            with ThreadPoolExecutor(max_workers=1) as pool:
                writing = pool.submit(add_turn, self.store, "selected")
                try:
                    self.assertIsNotNone(writing.result(timeout=2))
                    # A WAL reader keeps its original snapshot after that commit.
                    self.assertEqual(reader.execute("SELECT COUNT(*) FROM turns").fetchone()[0], 1)
                finally:
                    reader.rollback()
        self.assertEqual(len(self.store.get_history("selected", 10)), 2)

    def test_concurrent_initializers_and_writers_share_a_fresh_database(self):
        path = self.root / "concurrent.db"
        ready = threading.Barrier(6)

        def initialize(index):
            ready.wait(timeout=5)
            store = SessionStore(path)
            store.authorize(f"owned-{index}", "shared-owner", create=True)
            add_turn(store, f"owned-{index}")

        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = [pool.submit(initialize, index) for index in range(6)]
            for future in futures:
                future.result(timeout=10)
        self.assertEqual(len(SessionStore(path).list_conversations("shared-owner")), 6)

    def test_online_backup_preserves_wal_commits_owners_and_closed_sessions(self):
        # An idle connection need not attach to the WAL. Keep an actual read
        # snapshot open so commits cannot be checkpointed away during setup.
        with closing(self.store._connect()) as source:
            source.execute("PRAGMA wal_autocheckpoint=0")
            source.execute("BEGIN")
            source.execute("SELECT COUNT(*) FROM turns").fetchone()
            self.store.authorize("saved", "owner", create=True)
            add_turn(self.store, "saved")
            self.store.authorize("deleted", "owner", create=True)
            add_turn(self.store, "deleted")
            self.store.delete_history("deleted")
            self.assertGreater(Path(str(self.path) + "-wal").stat().st_size, 0)
            # The backup must see the newest commits, not our old read snapshot.
            source.rollback()
            backup = self.root / "backup.db"
            with closing(sqlite3.connect(backup)) as target:
                source.backup(target)
        restored = SessionStore(backup)
        self.assertEqual(len(restored.get_history("saved", 10, owner="owner")), 1)
        self.assertEqual([row["session_id"] for row in restored.list_conversations("owner")], ["saved"])
        self.assertTrue(restored.is_closed("deleted", owner="owner"))
        with self.assertRaises(SessionClosedError):
            add_turn(restored, "deleted")

    def test_busy_journal_switch_retries_but_other_failures_are_explicit(self):
        busy = sqlite3.OperationalError("database is locked")
        busy.sqlite_errorcode = sqlite3.SQLITE_BUSY
        conn = Mock()
        conn.execute.side_effect = [busy, Mock(fetchone=lambda: ("wal",))]
        with patch("core.session.time.sleep") as sleep:
            SessionStore._enable_wal(conn)
        sleep.assert_called_once()
        failure = sqlite3.OperationalError("read only")
        conn.execute.side_effect = failure
        with patch("core.session.time.sleep") as sleep:
            with self.assertRaisesRegex(sqlite3.OperationalError, "read only"):
                SessionStore._enable_wal(conn)
        sleep.assert_not_called()

    def test_busy_journal_switch_has_a_finite_deadline_and_no_silent_fallback(self):
        busy = sqlite3.OperationalError("database is locked")
        busy.sqlite_errorcode = sqlite3.SQLITE_BUSY
        conn = Mock()
        conn.execute.side_effect = busy
        with patch("core.session.time.monotonic", side_effect=[0.0, 6.0]):
            with self.assertRaises(sqlite3.OperationalError):
                SessionStore._enable_wal(conn)
        conn.execute.side_effect = None
        conn.execute.return_value.fetchone.return_value = ("delete",)
        with self.assertRaisesRegex(sqlite3.OperationalError, "WAL"):
            SessionStore._enable_wal(conn)
