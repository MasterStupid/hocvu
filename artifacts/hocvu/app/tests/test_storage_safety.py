from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.blob_storage import BlobStorage, safe_relative_path
from core.persistent_db import StorageUnavailable
from core.storage_backend import storage_backend, document_repository, session_store
from core.storage_transfer import import_backup
try:
    from tests.persistence_helpers import MemoryObjects
except ImportError:  # run via `unittest discover -s tests`
    from persistence_helpers import MemoryObjects


class StorageSafetyTests(unittest.TestCase):
    def test_published_local_mode_fails_instead_of_losing_data(self):
        with patch.dict("os.environ", {"REPLIT_DEPLOYMENT": "1", "HV_STORAGE_BACKEND": "local"}):
            with self.assertRaisesRegex(RuntimeError, "HV_STORAGE_BACKEND=replit"):
                storage_backend()

    def test_outage_never_falls_back_to_local_history_or_documents(self):
        with patch.dict("os.environ", {"HV_STORAGE_BACKEND": "replit"}):
            with patch("core.postgres_session.connect_database", side_effect=StorageUnavailable("database offline")):
                with self.assertRaises(StorageUnavailable):
                    session_store(Path("/must-not-create.db"))
            with patch("core.persistent_documents.PersistentDocumentRepository", side_effect=StorageUnavailable("storage offline")):
                with self.assertRaises(StorageUnavailable):
                    document_repository(Path("/must-not-create"))

    def test_import_needs_confirmation_and_never_targets_production(self):
        with self.assertRaises(StorageUnavailable):
            import_backup("does-not-exist.zip", apply=True)
        with patch.dict("os.environ", {"REPLIT_DEPLOYMENT": "1"}):
            with self.assertRaises(StorageUnavailable):
                import_backup("does-not-exist.zip", apply=True, confirmed=True)

    def test_path_traversal_and_corrupt_cache_are_not_trusted(self):
        for name in ("../outside", "/absolute", "folder/../outside", r"..\\outside", "./file"):
            with self.subTest(name=name), self.assertRaises(StorageUnavailable):
                safe_relative_path(name)
        client = MemoryObjects()
        blobs = BlobStorage(client=client, prefix="tests/files")
        descriptor = blobs.put(b"verified")
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "file.txt"
            path.write_bytes(b"corrupt local cache")
            blobs.materialize(Path(root), "file.txt", descriptor)
            self.assertEqual(path.read_bytes(), b"verified")
            client.items[descriptor["key"]] = b"corrupt remote file"
            path.unlink()
            with self.assertRaises(StorageUnavailable):
                blobs.materialize(Path(root), "file.txt", descriptor)
            self.assertFalse(path.exists())
