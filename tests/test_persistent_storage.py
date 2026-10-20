import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
from unittest.mock import patch
import zipfile

from core.blob_storage import BlobStorage
from core.documents import DocumentRepository
from core import engine as engine_module
from core.engine import HocVuEngine
from core.persistent_db import StorageUnavailable
from core.persistent_documents import DocumentState, PersistentDocumentRepository
from core.postgres_session import PostgresSessionStore
from core.session import SessionStore, SessionAccessError, SessionClosedError, LEGACY_API_OWNER
from core.settings import AppConfig
from core.storage_transfer import backup_local, backup_persistent, import_backup
from persistence_helpers import MemoryObjects, PostgresCase, add_turn, RESPONSE


TEXT = "## Điều 1. Hỗ trợ nghiên cứu\nSinh viên nghiên cứu được hỗ trợ 700000 đồng mỗi tháng."


class PersistentStorageTests(PostgresCase):
    def setUp(self):
        super().setUp()
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.source = self.root / "source"
        self.source.mkdir()
        self.client = MemoryObjects()
        self.blobs = BlobStorage(client=self.client, prefix="test/hocvu")
        self.state = DocumentState()
        self.repository = DocumentRepository(self.source / "documents")
        self.enterContext(patch.object(DocumentRepository, "extract", return_value=(TEXT, 1)))
        self.entry = self.repository.add(
            "nghien-cuu.pdf", b"%PDF-1.7 existing", metadata={"document_date": "2020-01-01"},
        )
        self.session = SessionStore(self.source / "sessions.db")
        self.session.authorize("hội thoại / 1?", "a" * 64, create=True)
        add_turn(self.session, "hội thoại / 1?")
        self.session.authorize("closed", "a" * 64, create=True)
        add_turn(self.session, "closed")
        self.session.delete_history("closed")
        add_turn(self.session, "legacy", response=None)
        self.backup = backup_local(self.source, output_dir=self.root / "backups")

    def migrate(self):
        return import_backup(self.backup["path"], apply=True, confirmed=True, blobs=self.blobs, state=self.state)

    def cloud_repo(self, directory="cache"):
        return PersistentDocumentRepository(self.root / directory / "documents", blobs=self.blobs, state=self.state)

    def engine(self, directory="cache"):
        root = self.root / directory
        root.mkdir(exist_ok=True)
        index = root / "index.json"
        self.enterContext(patch.dict("os.environ", {"HV_STORAGE_BACKEND": "replit"}))
        self.enterContext(patch.object(engine_module, "DOCS", root / "documents"))
        self.enterContext(patch.object(engine_module, "INDEX_JSON", index))
        self.enterContext(patch.object(engine_module, "AUD", root / "audio"))
        self.enterContext(patch.object(engine_module, "document_repository", lambda path: PersistentDocumentRepository(
            path, blobs=self.blobs, state=self.state,
        )))
        real_build = engine_module.build_index
        self.enterContext(patch.object(engine_module, "build_index", lambda config, **kwargs: real_build(
            config, index_path=kwargs.pop("index_path", index), **kwargs,
        )))
        return HocVuEngine.load_or_build(AppConfig(semantic_enabled=False), index)

    def test_backup_has_live_wal_snapshot_and_exact_ownership(self):
        reader = sqlite3.connect(self.source / "sessions.db")
        self.addCleanup(reader.close)
        reader.execute("BEGIN")
        reader.execute("SELECT * FROM turns").fetchall()
        add_turn(self.session, "hội thoại / 1?")
        latest = backup_local(self.source, output_dir=self.root / "backups")
        with zipfile.ZipFile(latest["path"]) as archive:
            self.assertIn("sessions.db", archive.namelist())
            history = json.loads(archive.read("history.json"))
            self.assertEqual(len(history["turns"]), 3)
            self.assertEqual(history["closed_sessions"], [{"session_id": "closed"}])
            self.assertEqual(history["session_owners"][1]["owner"], "a" * 64)
        self.assertEqual(Path(latest["path"]).stat().st_mode & 0o777, 0o600)

    def test_migration_is_atomic_idempotent_and_preserves_legacy_unknowns(self):
        dry = import_backup(self.backup["path"], blobs=self.blobs, state=self.state)
        self.assertFalse(dry["applied"])
        self.assertEqual(self.state.snapshot(initialized=False), (0, [], {}))
        migrated = self.migrate()
        self.assertTrue(migrated["applied"])
        self.assertIn(migrated["backup_key"], self.client.items)
        store = PostgresSessionStore()
        history = store.get_history("hội thoại / 1?", 10, owner="a" * 64)
        for key in ("references", "card", "confidence", "refused", "refusal_reason"):
            self.assertEqual(history[0][key], RESPONSE[key])
        self.assertIsNone(store.get_history("legacy", 10, owner=LEGACY_API_OWNER)[0]["references"])
        with self.assertRaises(SessionAccessError):
            store.get_history("legacy", 10, owner="b" * 64)
        with self.assertRaises(SessionClosedError):
            add_turn(store, "closed")
        self.assertGreater(add_turn(store, "hội thoại / 1?"), history[0]["id"])
        store.delete_history("hội thoại / 1?")
        repeat = self.migrate()
        self.assertTrue(repeat["already_imported"])
        self.assertTrue(store.is_closed("hội thoại / 1?"))
        self.assertEqual(store.get_history("hội thoại / 1?", 10, owner="a" * 64), [])

    def test_missing_storage_cannot_half_import_and_retry_works(self):
        self.client.fail = True
        with self.assertRaises(StorageUnavailable):
            self.migrate()
        self.assertEqual(self.state.snapshot(initialized=False), (0, [], {}))
        with self.connect() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM hv_turns").fetchone()[0], 0)
        self.client.fail = False
        self.assertTrue(self.migrate()["applied"])

    def test_existing_target_is_never_overwritten_by_other_backup(self):
        self.migrate()
        add_turn(self.session, "hội thoại / 1?")
        newer = backup_local(self.source, output_dir=self.root / "backups")
        with self.assertRaises(StorageUnavailable):
            import_backup(newer["path"], apply=True, confirmed=True, blobs=self.blobs, state=self.state)
        self.assertEqual(len(PostgresSessionStore().get_history("hội thoại / 1?", 10, owner="a" * 64)), 1)

    def test_cold_start_rebuilds_index_and_keeps_history_after_disk_is_removed(self):
        self.migrate()
        engine = self.engine()
        original = engine.documents.list()
        before = engine.searcher.search("hỗ trợ nghiên cứu", 100, "2026-10-20")
        self.assertTrue(any(hit.chunk.rid == self.entry["rid"] for hit in before))
        shutil.rmtree(self.root / "cache")
        restarted = self.engine()
        self.assertEqual(restarted.documents.list(), original)
        self.assertEqual(restarted.document_text(self.entry["id"])["text"], TEXT)
        self.assertEqual(len(restarted.history("hội thoại / 1?", owner="a" * 64)), 1)
        self.assertTrue(restarted.session.is_closed("closed", owner="a" * 64))
        self.assertFalse((self.root / "cache" / "sessions.db").exists())

    def test_upload_delete_and_date_edit_survive_cache_loss(self):
        self.migrate()
        engine = self.engine()
        new = engine.add_document(
            "second.pdf", b"%PDF-1.7 second", metadata={"document_date": "2020-01-01"},
        )
        engine.update_document_date(new["id"], "2026-10-01")
        engine.remove_document(self.entry["id"])
        shutil.rmtree(self.root / "cache")
        restarted = self.engine()
        self.assertEqual([row["id"] for row in restarted.documents.list()], [new["id"]])
        self.assertEqual(restarted.documents.list()[0]["document_date"], "2026-10-01")
        self.assertFalse(any(chunk.rid == self.entry["rid"] for chunk in restarted.searcher.chunks))

    def test_failed_cloud_commit_restores_manifest_index_and_live_searcher(self):
        self.migrate()
        engine = self.engine()
        index = self.root / "cache" / "index.json"
        before_index, before_state, before_searcher = index.read_bytes(), self.state.snapshot(), engine.searcher
        for operation in (
            lambda: engine.add_document("second.pdf", b"%PDF-1.7 second"),
            lambda: engine.remove_document(self.entry["id"]),
            lambda: engine.update_document_date(self.entry["id"], "2026-10-01"),
        ):
            with patch.object(engine.documents.state, "commit", side_effect=StorageUnavailable("commit failed")):
                with self.assertRaises(StorageUnavailable):
                    operation()
            self.assertEqual(self.state.snapshot(), before_state)
            self.assertEqual(engine.documents.list(), before_state[1])
            self.assertEqual(index.read_bytes(), before_index)
            self.assertIs(engine.searcher, before_searcher)
        self.assertTrue((engine.documents.root / self.entry["stored_name"]).exists())

    def test_reader_retries_after_failed_refresh_instead_of_marking_stale_index_current(self):
        self.migrate()
        engine = self.engine()
        remote = self.cloud_repo("remote-cache")
        with remote.change_date(self.entry["id"], "2026-10-01"):
            pass
        previous = engine._indexed_revision
        with patch.object(engine_module, "build_index", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                engine.list_documents()
        self.assertEqual(engine._indexed_revision, previous)
        engine.list_documents()
        self.assertEqual(engine._indexed_revision, self.state.revision())
        self.assertEqual(engine.documents.list()[0]["document_date"], "2026-10-01")

    def test_durable_backup_can_restore_into_an_empty_destination(self):
        self.migrate()
        repository = self.cloud_repo()
        backup = backup_persistent(repository, output_dir=self.root / "cloud-backups")
        self.assertIn(backup["backup_key"], self.client.items)
        with self.connect() as connection:
            # This is an isolated test schema, never the development/live tables.
            connection.execute("TRUNCATE hv_turns, hv_session_owners, hv_closed_sessions, hv_document_state, hv_storage_imports")
        result = import_backup(backup["path"], apply=True, confirmed=True, blobs=self.blobs, state=self.state)
        self.assertTrue(result["applied"])
        self.assertEqual(len(PostgresSessionStore().get_history("hội thoại / 1?", 10, owner="a" * 64)), 1)

    def test_corrupt_object_and_backup_are_rejected(self):
        self.migrate()
        _, _, objects = self.state.snapshot()
        descriptor = objects[self.entry["stored_name"]]
        self.client.items[descriptor["key"]] = b"bad bytes"
        with self.assertRaises(StorageUnavailable):
            self.cloud_repo().refresh()
        with zipfile.ZipFile(self.backup["path"]) as archive:
            items = {name: archive.read(name) for name in archive.namelist()}
        items["history.json"] = b'{"turns":[],"session_owners":[],"closed_sessions":[]}'
        corrupt = self.root / "corrupt.zip"
        with zipfile.ZipFile(corrupt, "w") as archive:
            for name, data in items.items():
                archive.writestr(name, data)
        with self.assertRaises(StorageUnavailable):
            import_backup(corrupt, blobs=self.blobs, state=self.state)
