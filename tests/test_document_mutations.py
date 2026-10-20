"""Upload/delete failures must leave metadata, files and search consistent."""
import errno
import shutil
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

    def batch(self):
        return [
            {"filename": f"batch-{i}.pdf", "content": f"%PDF-1.7 batch-{i}".encode(),
             "use_ocr": bool(i % 2), "metadata": {"order": str(i + 1), "document_date": "2020-01-01"}}
            for i in range(3)
        ]

    def test_batch_upload_writes_manifest_and_builds_once(self):
        with patch.object(self.repository, "_write_manifest", wraps=self.repository._write_manifest) as write:
            result = self.engine.add_documents(self.batch())
        self.build.assert_called_once()
        write.assert_called_once()
        self.assertEqual(len(result["items"]), 3)
        self.assertEqual(result["index"]["uploaded"], 4)
        self.assertEqual([item["order"] for item in result["items"]], [1, 2, 3])
        self.assertTrue(result["items"][1]["ocr"])
        for item in result["items"] + [self.existing]:
            self.assert_index_contains(item["rid"], True)

    def test_invalid_second_file_rolls_back_whole_batch_and_retry_works(self):
        for fault in ("signature", "duplicate", "metadata", "extraction"):
            with self.subTest(fault=fault):
                before, searcher = self.snapshot(), self.engine.searcher
                uploads = self.batch()
                if fault == "signature":
                    uploads[1]["content"] = b"bad"
                elif fault == "duplicate":
                    uploads[1]["content"] = uploads[0]["content"]
                elif fault == "metadata":
                    uploads[1]["metadata"]["document_date"] = "2026-02-30"
                extract = self.repository.extract.return_value
                side_effect = [extract, DocumentError("OCR failed")] if fault == "extraction" else None
                with patch.object(self.repository, "extract", return_value=extract, side_effect=side_effect):
                    with self.assertRaises(DocumentError):
                        self.engine.add_documents(uploads)
                self.assertEqual(self.snapshot(), before)
                self.assertIs(self.engine.searcher, searcher)
                self.build.assert_not_called()
        result = self.engine.add_documents(self.batch())
        self.assertEqual(len(result["items"]), 3)
        self.build.assert_called_once()

    def test_batch_storage_and_build_failures_keep_all_data_and_allow_retry(self):
        for mode in ("upload", "delete"):
            # A deletion of several existing documents, not just one item.
            if mode == "delete":
                self.engine.add_documents(self.batch())
            ids = [entry["id"] for entry in self.repository.list()]
            operation = (lambda: self.engine.add_documents(self.batch())) if mode == "upload" else (
                lambda: self.engine.remove_documents(ids)
            )
            for target in ("build", "manifest", "backup", "index-write", "index-lock", "snapshot"):
                with self.subTest(mode=mode, failure=target):
                    before, searcher = self.snapshot(), self.engine.searcher
                    if target == "build":
                        context = patch("core.engine.build_index", side_effect=RuntimeError("reindex failed"))
                    elif target == "manifest":
                        context = patch.object(self.repository, "_write_manifest", side_effect=OSError(errno.ENOSPC, "full"))
                    elif target == "backup":
                        original_copy = shutil.copy2
                        def copy(source, destination, *args, **kwargs):
                            if destination == self.repository.manifest_backup:
                                Path(destination).write_bytes(b"partial backup")
                                raise OSError(errno.ENOSPC, "full")
                            return original_copy(source, destination, *args, **kwargs)
                        context = patch("core.documents.shutil.copy2", side_effect=copy)
                    elif target == "snapshot":
                        context = patch("core.documents.shutil.copy2", side_effect=OSError(errno.ENOSPC, "full"))
                    else:
                        context = patch(
                            "core.searcher." + ("atomic_write" if target == "index-write" else "index_write_lock"),
                            side_effect=OSError(errno.ENOSPC, "full"),
                        )
                    with context, self.assertRaises((RuntimeError, OSError)):
                        operation()
                    self.assertEqual(self.snapshot(), before)
                    self.assertIs(self.engine.searcher, searcher)
            result = operation()
            if mode == "upload":
                self.assertEqual(len(result["items"]), 3)
                # Restore the starting corpus for the delete subtests.
                self.engine.remove_documents([item["id"] for item in result["items"]])
            else:
                self.assertEqual(result["deleted"], ids)
                self.assertEqual(self.repository.list(), [])

    def test_batch_rollback_needs_no_manifest_rewrite_on_full_disk(self):
        before = self.snapshot()
        write = self.repository._write_manifest
        for operation in (
            lambda: self.engine.add_documents(self.batch()),
            lambda: self.engine.remove_documents([self.existing["id"]]),
        ):
            with patch.object(self.repository, "_write_manifest") as writer:
                # Write once for real; subsequent attempts must fail.
                def write_once(entries):
                    if writer.call_count > 1:
                        raise OSError(errno.ENOSPC, "full")
                    write(entries)
                writer.side_effect = write_once
                with patch("core.engine.build_index", side_effect=OSError(errno.ENOSPC, "full")):
                    with self.assertRaises(OSError):
                        operation()
                self.assertEqual(writer.call_count, 1)
            self.assertEqual(self.snapshot(), before)

    def test_batch_delete_keeps_every_file_until_commit_and_builds_once(self):
        added = self.engine.add_documents(self.batch())["items"]
        self.build.reset_mock()
        selected = added + [self.existing]
        def rebuild(config, **kwargs):
            self.assertEqual(self.repository.list(), [])
            for item in selected:
                self.assertTrue((self.repository.root / item["stored_name"]).exists())
                self.assertTrue(self.repository._extracted_path(item["id"]).exists())
            return build_index(config, index_path=self.index, **kwargs)
        self.build.side_effect = rebuild
        result = self.engine.remove_documents([item["id"] for item in selected])
        self.build.assert_called_once()
        self.assertEqual(len(result["deleted"]), 4)
        for item in selected:
            self.assertFalse((self.repository.root / item["stored_name"]).exists())
            self.assertFalse(self.repository._extracted_path(item["id"]).exists())
            self.assert_index_contains(item["rid"], False)

    def test_post_commit_cleanup_failure_is_reported_without_false_rollback(self):
        source = self.repository.root / self.existing["stored_name"]
        unlink = Path.unlink
        def fail(path, *args, **kwargs):
            if path == source:
                raise PermissionError("locked")
            return unlink(path, *args, **kwargs)
        with patch.object(Path, "unlink", fail), self.assertLogs("core.documents", level="WARNING"):
            result = self.engine.remove_documents([self.existing["id"]])
        self.assertEqual(result["cleanup_pending"], [self.existing["id"]])
        self.assertEqual(self.repository.list(), [])
        self.assert_index_contains(self.existing["rid"], False)
        self.assertTrue(source.exists())

    def test_batch_limits_and_missing_or_duplicate_ids_change_nothing(self):
        before = self.snapshot()
        operations = [
            lambda: self.engine.add_documents([]),
            lambda: self.engine.add_documents(self.batch() * 7),
            lambda: self.engine.remove_documents([]),
            lambda: self.engine.remove_documents([self.existing["id"], "missing"]),
            lambda: self.engine.remove_documents([self.existing["id"]] * 2),
        ]
        for operation in operations:
            with self.assertRaises(DocumentError):
                operation()
            self.assertEqual(self.snapshot(), before)
        with patch.object(self.repository, "max_batch_bytes", 4), self.assertRaises(DocumentError):
            self.engine.add_documents(self.batch())
        self.build.assert_not_called()

    def test_partial_file_write_in_later_upload_is_cleaned(self):
        before = self.snapshot()
        write = Path.write_bytes
        calls = 0
        def fail(path, content):
            nonlocal calls
            calls += 1
            if calls == 2:
                write(path, b"partial")
                raise OSError(errno.ENOSPC, "full")
            return write(path, content)
        with patch.object(Path, "write_bytes", fail), self.assertRaises(OSError):
            self.engine.add_documents(self.batch())
        self.assertEqual(self.snapshot(), before)
        self.build.assert_not_called()
