import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from core.documents import DocumentRepository
from core.engine import HocVuEngine, build_index
from core.index_version import index_fingerprint
from core.searcher import HybridSearcher
from core.settings import AppConfig


class ManifestFreshnessTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.docs = self.root / "documents"
        self.index = self.root / "index.json"
        self.config = AppConfig(semantic_enabled=False)
        for target, value in (
            ("core.engine.DOCS", self.docs),
            ("core.index_version.DOCS", self.docs),
            ("core.engine.SESSION_DB", self.root / "sessions.db"),
            ("core.engine.AUD", self.root / "audio"),
        ):
            item = patch(target, value)
            item.start()
            self.addCleanup(item.stop)
        self.engine = HocVuEngine.load_or_build(self.config, self.index)
        self.repository = self.engine.documents

    def add(self, name="research"):
        text = "## Nghiên cứu thiên văn\nSinh viên nghiên cứu thiên văn được hỗ trợ 750000 đồng mỗi tháng."
        with patch.object(self.repository, "extract", return_value=(text, 1)):
            return self.repository.add(
                f"{name}.pdf", f"%PDF-1.7 {name}".encode(),
                metadata={"document_date": "2020-01-01", "article_clause": "Điều 4, Khoản 2"},
            )

    def rebuild(self):
        _, self.engine.searcher = build_index(self.config, return_searcher=True, index_path=self.index)

    def test_abrupt_process_exit_after_manifest_commit_is_repaired_on_next_startup(self):
        before = self.index.read_bytes()
        script = """
import os, sys
from pathlib import Path
from unittest.mock import patch
from core.documents import DocumentRepository
repository = DocumentRepository(Path(sys.argv[1]))
with patch.object(repository, 'extract', return_value=('## Nghiên cứu thiên văn\\nSinh viên nghiên cứu thiên văn được hỗ trợ mỗi tháng.', 1)):
    repository.add('interrupted.pdf', b'%PDF-1.7 interrupted', metadata={'document_date': '2020-01-01'})
os._exit(17)
"""
        result = subprocess.run(
            [sys.executable, "-c", script, str(self.docs)],
            capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(result.returncode, 17, result.stderr)
        self.assertEqual(self.index.read_bytes(), before)
        entry = self.repository.list()[0]
        with patch("core.engine.build_index", wraps=build_index) as build:
            restored = HocVuEngine.load_or_build(self.config, self.index)
            HocVuEngine.load_or_build(self.config, self.index)
        build.assert_called_once()
        self.assertTrue(any(chunk.rid == entry["rid"] for chunk in restored.searcher.chunks))
        item = next(item for item in restored.list_documents() if item.get("id") == entry["id"])
        self.assertGreater(item["chunk_count"], 0)

    def test_removed_document_is_not_served_after_restart(self):
        entry = self.add()
        self.rebuild()
        self.repository.remove(entry["id"])
        restored = HocVuEngine.load_or_build(self.config, self.index)
        self.assertFalse(any(chunk.rid == entry["rid"] for chunk in restored.searcher.chunks))
        self.assertFalse(any(item.get("id") == entry["id"] for item in restored.list_documents()))

    def test_out_of_band_metadata_changes_rebuild_citations_and_date_filters(self):
        entry = self.add()
        self.rebuild()
        entries = self.repository.list()
        entries[0].update(document_date="2030-01-01", article_clause="Điều 8, Khoản 3", title="Nguồn đã sửa")
        self.repository.manifest.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
        restored = HocVuEngine.load_or_build(self.config, self.index)
        chunks = [chunk for chunk in restored.searcher.chunks if chunk.rid == entry["rid"]]
        self.assertTrue(chunks)
        self.assertTrue(all(chunk.aid == "Điều 8" and chunk.clause_ids == ["3"] for chunk in chunks))
        self.assertTrue(all(chunk.valid_from == "2030-01-01" and chunk.reg_title == "Nguồn đã sửa" for chunk in chunks))
        hits = restored.searcher.search("hỗ trợ nghiên cứu thiên văn", 100, "2026-10-20")
        self.assertFalse(any(hit.chunk.rid == entry["rid"] for hit in hits))

    def test_build_fingerprint_matches_its_snapshot_not_a_later_manifest(self):
        first = self.add("first")
        self.rebuild()
        original = HybridSearcher.build
        added = []
        def concurrent_add(searcher, chunks):
            added.append(self.add("second"))
            return original(searcher, chunks)
        with patch.object(HybridSearcher, "build", concurrent_add):
            build_index(self.config, index_path=self.index)
        saved = json.loads(self.index.read_text())
        self.assertNotEqual(saved["index_fingerprint"], index_fingerprint(self.config))
        self.assertTrue(any(chunk["rid"] == first["rid"] for chunk in saved["chunks"]))
        self.assertFalse(any(chunk["rid"] == added[0]["rid"] for chunk in saved["chunks"]))
        restored = HocVuEngine.load_or_build(self.config, self.index)
        self.assertTrue(any(chunk.rid == added[0]["rid"] for chunk in restored.searcher.chunks))

    def test_extraction_upgrade_is_in_saved_fingerprint_without_a_rebuild_loop(self):
        self.add()
        entries = self.repository.list()
        entries[0]["extraction_version"] = 4
        self.repository._write_manifest(entries)
        with (
            patch.object(DocumentRepository, "extract", return_value=("## Nghiên cứu\nToàn văn nghiên cứu thiên văn còn nguyên.", 1)) as extract,
            patch("core.engine.build_index", wraps=build_index) as build,
        ):
            HocVuEngine.load_or_build(self.config, self.index)
            HocVuEngine.load_or_build(self.config, self.index)
        build.assert_called_once()
        extract.assert_called_once()
        self.assertEqual(json.loads(self.index.read_text())["index_fingerprint"], index_fingerprint(self.config))

    def test_json_formatting_does_not_create_false_staleness(self):
        self.add()
        self.rebuild()
        original = index_fingerprint(self.config)
        self.repository.manifest.write_text(
            json.dumps(self.repository.list(), ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        self.assertEqual(original, index_fingerprint(self.config))
        with patch("core.engine.build_index") as build:
            HocVuEngine.load_or_build(self.config, self.index)
        build.assert_not_called()

    def test_fingerprint_changes_for_add_delete_and_manifest_metadata(self):
        empty = index_fingerprint(self.config)
        self.add()
        populated = index_fingerprint(self.config)
        self.assertNotEqual(empty, populated)
        entries = self.repository.list()
        for field, value in (
            ("article_clause", "Điều 9"), ("document_date", "2030-01-01"),
            ("title", "New title"), ("order", 9), ("ocr", True), ("stored_name", "other.pdf"),
        ):
            with self.subTest(field=field):
                changed = [{**entries[0], field: value}]
                self.assertNotEqual(populated, index_fingerprint(self.config, document_entries=changed))
        self.repository.manifest.unlink()
        self.assertEqual(empty, index_fingerprint(self.config))

    def test_missing_and_empty_manifest_are_equivalent(self):
        original = index_fingerprint(self.config)
        self.repository.manifest.write_text("[]", encoding="utf-8")
        self.assertEqual(original, index_fingerprint(self.config))
