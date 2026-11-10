"""Opt-in cloud check; isolated schema/prefix, no application data is imported."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid

try:
    from tests.persistence_helpers import PostgresCase
except ImportError:
    from persistence_helpers import PostgresCase


class LivePersistentStorageTests(PostgresCase):
    def test_real_objects_and_history_survive_process_restart_and_cache_loss(self):
        if os.environ.get("HV_TEST_APP_STORAGE") != "1":
            self.skipTest("Set HV_TEST_APP_STORAGE=1 for real project App Storage operations")
        from core.blob_storage import BlobStorage
        with self.connect() as connection:
            schema = connection.execute("SELECT current_schema()").fetchone()[0]
        prefix = "hocvu-checks/" + uuid.uuid4().hex
        blobs = BlobStorage(prefix=prefix)

        def cleanup():
            # Delete only this run's objects; never touch the app's prefix.
            for item in blobs.client.list(prefix=prefix + "/"):
                blobs.client.delete(item.name)
        self.addCleanup(cleanup)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / "cache"
            environment = {
                **os.environ, "PGOPTIONS": f"-c search_path={schema}",
                "HV_STORAGE_BACKEND": "replit", "HV_STORAGE_PREFIX": prefix,
                "HV_DATA_DIR": str(cache), "HV_SEMANTIC": "0",
            }
            for phase in ("write", "read"):
                result = subprocess.run(
                    [sys.executable, "-m", "tests.helpers.persistent_restart", phase, str(root / "result.json")],
                    cwd=Path(__file__).resolve().parents[1], env=environment,
                    capture_output=True, text=True, timeout=150,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                if phase == "write":
                    shutil.rmtree(cache)
