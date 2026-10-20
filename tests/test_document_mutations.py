"""Upload/delete failures must leave metadata, files and search consistent."""
import errno
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.documents import DocumentError, DocumentRepository
from core.engine import HocVuEngine, build_index
from core.searcher import HybridSearcher
from core.settings import AppConfig


class DocumentMutationTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.index = self.root / "index.json"
        self.repository = DocumentRepository(self.root / "documents")
        self.enterContext(patch("core.engine.DOCS", self.repository.root))
        self.enterContext(patch.object(self.repository, "extract", return_value=(
            "## Hỗ trợ nghiên cứu\nSinh viên nghiên cứu được hỗ trợ 700000 đồng mỗi tháng.", 1,
        )))
        self.existing = self.repository.add(
            "existing.pdf", b"%PDF-1.7 existing", metadata={"document_date": "2020-01-01"},
        )
        # Start with both an active manifest and a known-good backup.
        self.repository._write_manifest(self.repository.list())
        self.config = AppConfig(semantic_enabled=False)
        _, searcher = build_index(self.config, return_searcher=True, index_path=self.index)
        # These operations do not need voice/session stores or server startup.
        self.engine = HocVuEngine.__new__(HocVuEngine)
        self.engine.config = self.config
        self.engine.documents = self.repository
        self.engine.searcher = searcher
        self.build = self.enterContext(patch(
            "core.engine.build_index",
            side_effect=lambda config, **kwargs: build_index(config, index_path=self.index, **kwargs),
        ))

    def snapshot(self):
        return {
            str(path.relative_to(self.root)): path.read_bytes()
            for path in self.root.rglob("*") if path.is_file()
        }

    def upload(self):
        return self.engine.add_document(
            "new.pdf", b"%PDF-1.7 new", metadata={"document_date": "2020-01-01"},
        )

    def assert_index_contains(self, rid, expected):
        for searcher in (self.engine.searcher, HybridSearcher.load(str(self.index), self.config)):
            self.assertEqual(any(chunk.rid == rid for chunk in searcher.chunks), expected)

    def test_failed_upload_restores_manifest_backup_files_and_live_index(self):
        before, searcher = self.snapshot(), self.engine.searcher
        for error in (RuntimeError("build failure"), OSError(errno.ENOSPC, "disk full")):
            with self.subTest(error=type(error).__name__):
                self.build.side_effect = error
                with self.assertRaises(type(error)):
                    self.upload()
                self.assertEqual(self.snapshot(), before)
                self.assertIs(self.engine.searcher, searcher)
                self.assertEqual(list(self.repository.root.glob(".manifest-*")), [])

    def test_failed_delete_retains_original_and_extracted_files_throughout_build(self):
        before, searcher = self.snapshot(), self.engine.searcher
        original = self.repository.root / self.existing["stored_name"]
        extracted = self.repository._extracted_path(self.existing["id"])

        def fail(*args, **kwargs):
            self.assertEqual(self.repository.list(), [])
            self.assertTrue(original.is_file())
            self.assertTrue(extracted.is_file())
            raise OSError(errno.ENOSPC, "disk full")

        self.build.side_effect = fail
        with self.assertRaises(OSError):
            self.engine.remove_document(self.existing["id"])
        self.assertEqual(self.snapshot(), before)
        self.assertIs(self.engine.searcher, searcher)
        self.assert_index_contains(self.existing["rid"], True)

    def test_real_index_write_and_lock_failures_rollback_both_operations(self):
        for target in ("core.searcher.atomic_write", "core.searcher.index_write_lock"):
            for operation in (self.upload, lambda: self.engine.remove_document(self.existing["id"])):
                with self.subTest(target=target, operation=operation):
                    before, searcher = self.snapshot(), self.engine.searcher
                    with patch(target, side_effect=OSError("index storage failure")):
                        with self.assertRaises(OSError):
                            operation()
                    self.assertEqual(self.snapshot(), before)
                    self.assertIs(self.engine.searcher, searcher)

    def test_rollback_does_not_rewrite_json_when_the_disk_is_full(self):
        before = self.snapshot()

        def fail(*args, **kwargs):
            # Further JSON writes would fail too: rollback must use its staged copy.
            with patch.object(self.repository, "_write_manifest", side_effect=OSError(errno.ENOSPC, "full")):
                raise OSError(errno.ENOSPC, "full")

        # Keep the simulated disk failure active while the exception unwinds.
        original_write = self.repository._write_manifest
        writes = 0

        def write_once(entries):
            nonlocal writes
            writes += 1
            if writes > 1:
                raise OSError(errno.ENOSPC, "full")
            return original_write(entries)

        self.build.side_effect = fail
        with patch.object(self.repository, "_write_manifest", side_effect=write_once):
            with self.assertRaises(OSError):
                self.upload()
        self.assertEqual(writes, 1)
        self.assertEqual(self.snapshot(), before)

    def test_manifest_write_failures_do_not_leave_uploads_or_delete_originals(self):
        for operation in (self.upload, lambda: self.engine.remove_document(self.existing["id"])):
            before = self.snapshot()
            with patch.object(self.repository, "_write_manifest", side_effect=OSError("manifest full")):
                with self.assertRaises(OSError):
                    operation()
            self.assertEqual(self.snapshot(), before)
        self.build.assert_not_called()

    def test_extraction_failure_cleans_upload_without_touching_existing_data(self):
        before = self.snapshot()
        with patch.object(self.repository, "extract", side_effect=DocumentError("cannot extract")):
            with self.assertRaises(DocumentError):
                self.upload()
        self.assertEqual(self.snapshot(), before)
        self.build.assert_not_called()

    def test_failed_first_upload_restores_absent_manifest_and_backup(self):
        self.engine.documents = DocumentRepository(self.root / "empty")
        self.build.side_effect = RuntimeError("failed")
        with patch.object(self.engine.documents, "extract", return_value=("Nội dung văn bản đủ dài để lập chỉ mục.", 1)):
            before = self.snapshot()
            with self.assertRaises(RuntimeError):
                self.upload()
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.engine.documents.manifest.exists())
        self.assertFalse(self.engine.documents.manifest_backup.exists())

    def test_successful_upload_commits_files_and_live_and_saved_index(self):
        searcher = self.engine.searcher
        entry = self.upload()
        self.assertIsNot(self.engine.searcher, searcher)
        self.assertTrue((self.repository.root / entry["stored_name"]).is_file())
        self.assertTrue(self.repository._extracted_path(entry["id"]).is_file())
        self.assertEqual(len(self.repository.list()), 2)
        self.assert_index_contains(entry["rid"], True)
        self.assert_index_contains(self.existing["rid"], True)

    def test_successful_delete_cleans_files_only_after_index_commit(self):
        original = self.repository.root / self.existing["stored_name"]
        extracted = self.repository._extracted_path(self.existing["id"])

        def rebuild(config, **kwargs):
            self.assertTrue(original.is_file())
            self.assertTrue(extracted.is_file())
            return build_index(config, index_path=self.index, **kwargs)

        self.build.side_effect = rebuild
        self.engine.remove_document(self.existing["id"])
        self.assertEqual(self.repository.list(), [])
        self.assertFalse(original.exists())
        self.assertFalse(extracted.exists())
        self.assert_index_contains(self.existing["rid"], False)

    def test_failed_upload_can_be_retried_without_false_duplicate(self):
        rebuild = self.build.side_effect
        self.build.side_effect = RuntimeError("failed")
        with self.assertRaises(RuntimeError):
            self.upload()
        self.build.side_effect = rebuild
        entry = self.upload()
        self.assertEqual(len(self.repository.list()), 2)
        self.assert_index_contains(entry["rid"], True)

    def test_missing_delete_does_not_reindex_or_change_data(self):
        before = self.snapshot()
        with self.assertRaises(DocumentError):
            self.engine.remove_document("missing")
        self.assertEqual(self.snapshot(), before)
        self.build.assert_not_called()
