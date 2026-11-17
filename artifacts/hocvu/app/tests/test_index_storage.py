import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core.index_storage import index_write_lock


class WindowsIndexLockTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.destination = self.root / "index.json"
        self.lock_path = self.root / "index.json.lock"
        self.windows = SimpleNamespace(LK_NBLCK=1, LK_UNLCK=2, locking=Mock())
        self.enterContext(patch.dict(sys.modules, {"msvcrt": self.windows}))
        self.enterContext(patch("core.index_storage.os.name", "nt"))

    def test_repeated_locks_never_append_bytes(self):
        for _ in range(100):
            with index_write_lock(self.destination):
                self.assertEqual(self.lock_path.read_bytes(), b"\0")
        self.assertEqual(self.windows.locking.call_count, 200)
        self.assertEqual(self.lock_path.stat().st_size, 1)

    def test_existing_lock_file_is_not_truncated_or_extended(self):
        self.lock_path.write_bytes(b"existing")
        with index_write_lock(self.destination):
            self.assertEqual(self.lock_path.read_bytes(), b"existing")
        self.assertEqual(self.lock_path.read_bytes(), b"existing")

    def test_busy_lock_retries_without_writing_and_always_unlocks(self):
        self.windows.locking.side_effect = [OSError("busy"), None, None]
        with patch("core.index_storage.time.sleep") as sleep:
            with self.assertRaisesRegex(RuntimeError, "test failure"):
                with index_write_lock(self.destination):
                    raise RuntimeError("test failure")
        sleep.assert_called_once_with(0.05)
        self.assertEqual(self.windows.locking.call_args.args[1], self.windows.LK_UNLCK)
        self.assertEqual(self.lock_path.stat().st_size, 1)
