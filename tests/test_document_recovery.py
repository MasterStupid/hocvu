"""Legacy date recovery must be selective, offline, and non-destructive."""
import contextlib
import copy
import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import manage
from core.document_recovery import recover_document_dates
from core.documents import DocumentError, DocumentRepository
from core.engine import HocVuEngine, build_index
from core.index_storage import atomic_write
from core.searcher import HybridSearcher
from core.settings import AppConfig


def docx_bytes(marker):
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w") as archive:
        archive.writestr("word/document.xml", (
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:body><w:p><w:r><w:t>Điều kiện bảo lưu học tập</w:t></w:r></w:p>'
            f'<w:p><w:r><w:t>Sinh viên {marker} được bảo lưu tối đa bốn học kỳ.</w:t></w:r></w:p>'
            '</w:body></w:document>'
        ))
    return content.getvalue()


class DocumentRecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repo = DocumentRepository(self.root / "documents")
        self.index = self.root / "index" / "index.json"
        self.server_meta = self.root / "server.json"
        self.config = AppConfig(semantic_enabled=False)
        for number in range(4):
            self.repo.add(
                f"quy_che_{number}.docx", docx_bytes(number),
                metadata={"document_date": "2026-01-01" if number != 3 else "", "order": 4 - number},
            )
        self.entries = self.repo._read_manifest()
        self.entries[0]["document_date"] = "2026-02-31"
        self.entries[1]["document_date"] = "2026-10-35"
        for entry in self.entries:
            entry["extraction_version"] = 0
            entry["custom_metadata"] = {"do_not_touch": ["kept", 7]}
        self.repo._write_manifest(self.entries)
        self.build_current_index()
        self.plan = {
            "manifest_sha256": self.repo.audit_document_dates()["manifest_sha256"],
            "corrections": [{"id": self.entries[0]["id"], "document_date": "2024-02-29"}],
        }

    def build_current_index(self):
        entries = self.repo._read_manifest()
        return build_index(
            self.config, index_path=self.index,
            uploaded_regulations=self.repo.regulations(
                entries=entries, refresh_extraction=False,
            ),
            document_entries=entries,
        )

    def recover(self, **kwargs):
        return recover_document_dates(
            self.config, self.repo, self.index, self.plan, server_meta=self.server_meta, **kwargs,
        )

    def snapshot(self):
        return {path.relative_to(self.root): path.read_bytes()
                for path in self.root.rglob("*") if path.is_file()}

    def test_audit_finds_invalid_calendar_dates_without_reading_or_logging_text(self):
        before = self.snapshot()
        with patch.object(self.repo, "extract") as extract:
            report = self.repo.audit_document_dates()
        self.assertEqual(report["total"], 4)
        self.assertEqual(report["affected_count"], 2)
        self.assertEqual({item["id"] for item in report["affected"]},
                         {entry["id"] for entry in self.entries[:2]})
        self.assertEqual({item["issue"] for item in report["affected"]}, {"invalid_calendar_date"})
        self.assertNotIn("title", json.dumps(report))
        self.assertNotIn("Sinh viên", json.dumps(report))
        self.assertEqual(self.snapshot(), before)
        extract.assert_not_called()

    def test_dry_run_does_not_rebuild_or_change_any_file(self):
        before = self.snapshot()
        with patch("core.document_recovery.build_index") as build:
            result = self.recover()
        self.assertEqual(result["mode"], "dry_run")
        self.assertEqual(result["selected_count"], 1)
        self.assertEqual(self.snapshot(), before)
        build.assert_not_called()

    def test_selected_recovery_preserves_all_other_metadata_and_originals(self):
        original = self.snapshot()
        old_index = HybridSearcher.load(str(self.index), self.config)
        target = self.entries[0]
        self.assertFalse(any(hit.chunk.rid == target["rid"]
                             for hit in old_index.search("bảo lưu", 100, "2024-02-29")))
        with patch.object(self.repo, "extract") as extract:
            result = self.recover(apply=True, confirmed=True)
        extract.assert_not_called()
        self.assertEqual(result["mode"], "applied")
        check = result["verification"][0]
        self.assertFalse(check["visible_before_repair"])
        self.assertFalse(check["visible_before"])
        self.assertTrue(check["visible_on"])
        self.assertTrue(check["visible_after"])
        changed = copy.deepcopy(self.entries)
        changed[0]["document_date"] = "2024-02-29"
        self.assertEqual(self.repo._read_manifest(), changed)
        self.assertEqual(self.repo.audit_document_dates()["affected_count"], 1)
        for path, content in original.items():
            if path.suffix in {".docx", ".txt"}:
                self.assertEqual((self.root / path).read_bytes(), content)
        self.assertEqual(self.repo.manifest_backup.read_bytes(), original[Path("documents/manifest.json")])
        self.assertEqual(self.index.with_suffix(".json.bak").read_bytes(), original[Path("index/index.json")])
        new_index = HybridSearcher.load(str(self.index), self.config)
        for reference, visible in (("2024-02-28", False), ("2024-02-29", True), ("2024-03-01", True)):
            self.assertEqual(
                any(hit.chunk.rid == target["rid"] for hit in new_index.search("bảo lưu", 100, reference)),
                visible,
            )
        original_other = [chunk.to_dict() for chunk in old_index.chunks if chunk.rid != target["rid"]]
        repaired_other = [chunk.to_dict() for chunk in new_index.chunks if chunk.rid != target["rid"]]
        self.assertEqual(original_other, repaired_other)
        self.assertFalse(any(hit.chunk.rid == self.entries[1]["rid"]
                             for hit in new_index.search("bảo lưu", 100, "2026-11-01")))
        with (
            patch("core.engine.DOCS", self.repo.root),
            patch("core.engine.SESSION_DB", self.root / "session.db"),
            patch("core.engine.AUD", self.root / "audio"),
            patch("core.engine.build_index", wraps=build_index) as build,
        ):
            engine = HocVuEngine.load_or_build(self.config, self.index)
        build.assert_not_called()
        self.assertTrue(any(hit.chunk.rid == target["rid"]
                            for hit in engine.searcher.search("bảo lưu", 100, "2024-02-29")))

    def test_batch_repair_and_repeat_is_rejected_without_writes(self):
        self.plan["corrections"].append({"id": self.entries[1]["id"], "document_date": "2026-10-25"})
        self.assertEqual(self.recover(apply=True, confirmed=True)["selected_count"], 2)
        self.assertEqual(self.repo.audit_document_dates()["affected_count"], 0)
        before = self.snapshot()
        with self.assertRaises(DocumentError):
            self.recover(apply=True, confirmed=True)
        self.assertEqual(self.snapshot(), before)

    def test_calendar_extremes_do_not_overflow_verification(self):
        for effective in ("0001-01-01", "9999-12-31"):
            with self.subTest(effective=effective):
                self.plan["corrections"][0]["document_date"] = effective
                # Reset only the legacy metadata and regenerate its audit token.
                self.repo._write_manifest(self.entries)
                self.plan["manifest_sha256"] = self.repo.audit_document_dates()["manifest_sha256"]
                result = self.recover(apply=True, confirmed=True)
                self.assertTrue(result["verification"][0]["visible_on"])

    def test_invalid_or_unselected_plans_never_write(self):
        invalid_plans = [
            None, [], {}, {"manifest_sha256": "stale", "corrections": self.plan["corrections"]},
            {**self.plan, "corrections": []},
            {**self.plan, "corrections": [{"id": "unknown", "document_date": "2026-02-28"}]},
            {**self.plan, "corrections": self.plan["corrections"] * 2},
            {**self.plan, "corrections": [{"id": self.entries[2]["id"], "document_date": "2026-02-28"}]},
            {**self.plan, "corrections": [{"id": self.entries[3]["id"], "document_date": "2026-02-28"}]},
        ]
        invalid_plans.extend(
            {**self.plan, "corrections": [{"id": self.entries[0]["id"], "document_date": value}]}
            for value in ("2026-02-31", "2025-02-29", "20261004", "", None, 20260101, [], " 2026-01-01")
        )
        invalid_plans.append({**self.plan, "corrections": [
            {**self.plan["corrections"][0], "title": "must not change"},
        ]})
        before = self.snapshot()
        for plan in invalid_plans:
            with self.subTest(plan=plan):
                with self.assertRaises(DocumentError):
                    recover_document_dates(self.config, self.repo, self.index, plan, server_meta=self.server_meta,
                                           apply=True, confirmed=True)
                self.assertEqual(self.snapshot(), before)

    def test_administrator_confirmation_and_stopped_server_are_required(self):
        before = self.snapshot()
        with self.assertRaisesRegex(DocumentError, "confirm"):
            self.recover(apply=True)
        self.assertEqual(self.snapshot(), before)
        self.server_meta.write_text(json.dumps({"pid": os.getpid()}))
        before = self.snapshot()
        with self.assertRaisesRegex(DocumentError, "dừng máy chủ"):
            self.recover(apply=True, confirmed=True)
        self.assertEqual(self.snapshot(), before)

    def test_build_or_verification_failure_leaves_every_file_unchanged(self):
        before = self.snapshot()
        for target in ("build_index", "_verify_dates"):
            with self.subTest(target=target):
                with patch(f"core.document_recovery.{target}", side_effect=DocumentError("synthetic failure")):
                    with self.assertRaises(DocumentError):
                        self.recover(apply=True, confirmed=True)
                self.assertEqual(self.snapshot(), before)

    def test_missing_or_corrupt_previous_index_is_reported_and_good_backup_survives(self):
        for missing in (False, True):
            with self.subTest(missing=missing):
                self.repo._write_manifest(self.entries)
                self.plan["manifest_sha256"] = self.repo.audit_document_dates()["manifest_sha256"]
                self.build_current_index()
                backup = self.index.with_suffix(".json.bak")
                backup.write_bytes(self.index.read_bytes())
                good_backup = backup.read_bytes()
                if missing:
                    self.index.unlink()
                else:
                    self.index.write_bytes(b"{broken")
                result = self.recover(apply=True, confirmed=True)
                self.assertEqual(result["previous_index_status"], "missing" if missing else "unreadable")
                self.assertIsNone(result["verification"][0]["visible_before_repair"])
                self.assertEqual(backup.read_bytes(), good_backup)
                self.assertTrue(HybridSearcher.load(str(self.index), self.config).chunks)

    def test_legacy_nonstring_dates_are_repaired_without_failing_open(self):
        for value in (123, ["bad"], {"bad": "date"}):
            with self.subTest(value=value):
                entries = copy.deepcopy(self.entries)
                entries[0]["document_date"] = value
                self.repo._write_manifest(entries)
                self.plan["manifest_sha256"] = self.repo.audit_document_dates()["manifest_sha256"]
                self.build_current_index()
                result = self.recover(apply=True, confirmed=True)
                self.assertFalse(result["verification"][0]["visible_before_repair"])
                self.assertEqual(self.repo._read_manifest()[0]["document_date"], "2024-02-29")

    def test_index_commit_failure_rolls_back_manifest_index_and_backups(self):
        before = self.snapshot()
        failed = False

        def write(path, content):
            nonlocal failed
            if path == self.index and not failed:
                failed = True
                raise OSError("synthetic disk error")
            atomic_write(path, content)

        with patch("core.document_recovery.atomic_write", side_effect=write):
            with self.assertRaisesRegex(DocumentError, "hoàn tác"):
                self.recover(apply=True, confirmed=True)
        self.assertEqual(self.snapshot(), before)

    def test_stale_manifest_change_during_build_is_not_overwritten(self):
        original_build = build_index

        def build(*args, **kwargs):
            result = original_build(*args, **kwargs)
            entries = self.repo._read_manifest()
            entries[2]["title"] = "Concurrent administrator update"
            self.repo._write_manifest(entries)
            return result

        index_before = self.index.read_bytes()
        with patch("core.document_recovery.build_index", side_effect=build):
            with self.assertRaisesRegex(DocumentError, "đã thay đổi"):
                self.recover(apply=True, confirmed=True)
        self.assertEqual(self.repo._read_manifest()[2]["title"], "Concurrent administrator update")
        self.assertEqual(self.repo._read_manifest()[0]["document_date"], "2026-02-31")
        self.assertEqual(self.index.read_bytes(), index_before)

    def test_missing_original_prevents_repair_even_if_extracted_text_exists(self):
        (self.repo.root / self.entries[0]["stored_name"]).unlink()
        before = self.snapshot()
        with self.assertRaisesRegex(DocumentError, "Thiếu tệp gốc"):
            self.recover(apply=True, confirmed=True)
        self.assertEqual(self.snapshot(), before)


class DocumentDateAuditTests(unittest.TestCase):
    def test_legacy_values_are_classified_without_guessing(self):
        for value in ("2026-02-31", "2026-10-35", "2025-02-29", "1900-02-29",
                      "0000-01-01", "2026-00-01", "2026-13-01", "2026-01-00",
                      "not-a-date", "20261004", "2026-W01-1", " ", False, 123, [], {}):
            with self.subTest(value=value):
                self.assertIsNotNone(DocumentRepository.document_date_issue(value))
        for value in (None, "", "2024-02-29", "2000-02-29", "0001-01-01", "9999-12-31", "2026-10-04"):
            with self.subTest(value=value):
                self.assertIsNone(DocumentRepository.document_date_issue(value))

    def test_missing_repository_audit_does_not_create_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "not-created"
            report = DocumentRepository(root, create_dirs=False).audit_document_dates()
            self.assertEqual(report["total"], 0)
            self.assertEqual(report["affected_count"], 0)
            self.assertFalse(root.exists())

    def test_broken_manifest_does_not_restore_backup_during_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = DocumentRepository(Path(directory))
            repo.manifest.write_text("{broken")
            repo.manifest_backup.write_text("[]")
            with self.assertRaises(DocumentError):
                repo.audit_document_dates()
            self.assertEqual(repo.manifest.read_text(), "{broken")
            self.assertEqual(repo.manifest_backup.read_text(), "[]")

    def test_cli_prints_count_first_dry_runs_and_requires_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            docs = root / "documents"
            docs.mkdir()
            (docs / "manifest.json").write_text(json.dumps([
                {"id": "legacy", "rid": "UPL-LEGACY", "document_date": "2026-02-31", "text": "PRIVATE BODY"},
            ]))
            repo = DocumentRepository(docs, create_dirs=False)
            plan = root / "plan.json"
            plan.write_text(json.dumps({
                "manifest_sha256": repo.audit_document_dates()["manifest_sha256"],
                "corrections": [{"id": "legacy", "document_date": "2026-02-28"}],
            }))
            for args, fails in (
                (["audit-document-dates"], False),
                (["repair-document-dates", "--plan", str(plan)], False),
                (["repair-document-dates", "--plan", str(plan), "--apply"], True),
            ):
                with self.subTest(args=args):
                    output, errors = io.StringIO(), io.StringIO()
                    with (
                        patch("sys.argv", ["manage.py", *args]),
                        patch("manage.DOCS", docs),
                        patch("manage.ensure_dirs") as ensure,
                        contextlib.redirect_stdout(output),
                        contextlib.redirect_stderr(errors),
                    ):
                        if fails:
                            with self.assertRaises(SystemExit):
                                manage.main()
                        else:
                            manage.main()
                    ensure.assert_not_called()
                    self.assertEqual(json.loads(output.getvalue().splitlines()[0])["affected_count"], 1)
                    self.assertNotIn("PRIVATE BODY", output.getvalue() + errors.getvalue())
                    self.assertNotIn("2026-02-31", output.getvalue())
                    self.assertEqual(repo._read_manifest()[0]["document_date"], "2026-02-31")
