"""Automatic index refresh must behave the same for the server and CLI."""
import contextlib
import io
import json
import multiprocessing
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

import manage
from core.corpus import build_corpus
from core.documents import DocumentRepository
from core.engine import HocVuEngine, build_index
from core.index_version import INDEX_SOURCE_FILES, index_fingerprint
from core.searcher import HybridSearcher, StaleIndexError
from core.settings import AppConfig


def _rebuild_worker(root, role, seed, entered, paused, release, stage="primary"):
    """Run real server startup/CLI ingest with a controlled commit boundary."""
    root = Path(root)
    index = root / "custom" / "index.json"
    config = AppConfig(semantic_enabled=False, seed=seed)
    original_save = HybridSearcher.save
    original_replace = os.replace

    def save(searcher, *args, **kwargs):
        entered.set()
        return original_save(searcher, *args, **kwargs)

    def replace_file(source, destination):
        target = index.with_suffix(".json.bak") if stage == "backup" else index
        if Path(destination) == target:
            if stage == "committed":
                original_replace(source, destination)
            paused.set()
            if not release.wait(20):
                raise RuntimeError("Test did not release paused index writer")
            if stage == "committed":
                return
        return original_replace(source, destination)

    with (
        patch("core.engine.DOCS", root / "documents"),
        patch("core.engine.SESSION_DB", root / f"sessions-{role}.db"),
        patch.object(HybridSearcher, "save", save),
        patch("core.index_storage.os.replace", replace_file),
    ):
        if role == "server":
            HocVuEngine.load_or_build(config, index)
        else:
            with (
                patch("sys.argv", ["manage.py", "ingest"]),
                patch("manage.load_config", return_value=config),
                patch("manage.ensure_dirs"),
                patch("manage.build_index", side_effect=lambda cfg: build_index(cfg, index_path=index)),
            ):
                manage.main()


class IndexFreshnessTests(unittest.TestCase):
    def test_public_load_rebuilds_stale_index_once(self):
        HocVuEngine.load(self.config, self.index)
        self.sources[0].write_bytes(self.sources[0].read_bytes() + b"\n# changed source\n")
        with patch("core.engine.build_index", wraps=build_index) as build:
            HocVuEngine.load(self.config, self.index)
            HocVuEngine.load(self.config, self.index)
        build.assert_called_once()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.index = self.root / "custom" / "index.json"
        self.config = AppConfig(semantic_enabled=False)
        self.sources = []
        for source in INDEX_SOURCE_FILES:
            copy = self.root / source.name
            copy.write_bytes(source.read_bytes())
            self.sources.append(copy)
        for patcher in (
            patch("core.index_version.INDEX_SOURCE_FILES", tuple(self.sources)),
            patch("core.engine.DOCS", self.root / "documents"),
            patch("core.engine.SESSION_DB", self.root / "sessions.db"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_fingerprint_changes_for_each_source_not_its_timestamp(self):
        original = index_fingerprint(self.config)
        self.assertEqual(original, index_fingerprint(replace(self.config)))
        for source in self.sources:
            with self.subTest(source=source.name):
                contents = source.read_bytes()
                source.touch()
                self.assertEqual(original, index_fingerprint(self.config))
                source.write_bytes(contents + b"\n# Changed indexing rules\n")
                self.assertNotEqual(original, index_fingerprint(self.config))
                source.write_bytes(contents)

    def test_fingerprint_tracks_chunk_settings_but_not_query_settings(self):
        original = index_fingerprint(self.config)
        for setting, value in (("seed", 7), ("max_chunk_chars", 120), ("overlap_sents", 0)):
            with self.subTest(setting=setting):
                self.assertNotEqual(original, index_fingerprint(replace(self.config, **{setting: value})))
        self.assertEqual(original, index_fingerprint(replace(self.config, top_k=99)))

    def test_missing_index_is_built_at_requested_path_and_reused(self):
        with patch("core.engine.build_index", wraps=build_index) as build:
            first = HocVuEngine.load_or_build(self.config, self.index)
            second = HocVuEngine.load_or_build(self.config, self.index)
        build.assert_called_once()
        saved = json.loads(self.index.read_text(encoding="utf-8"))
        self.assertEqual(saved["article_version"], DocumentRepository.article_build_version())
        self.assertEqual(saved["index_fingerprint"], index_fingerprint(self.config))
        self.assertEqual(first.searcher.chunks, second.searcher.chunks)

    def test_each_source_change_triggers_only_one_rebuild(self):
        HocVuEngine.load_or_build(self.config, self.index)
        for source in self.sources:
            with self.subTest(source=source.name):
                source.write_bytes(source.read_bytes() + b"\n# Update\n")
                with patch("core.engine.build_index", wraps=build_index) as build:
                    HocVuEngine.load_or_build(self.config, self.index)
                    HocVuEngine.load_or_build(self.config, self.index)
                build.assert_called_once()

    def test_rebuild_serves_updated_wording_and_citations(self):
        HocVuEngine.load_or_build(self.config, self.index)
        corpus = build_corpus()
        clause = corpus[0].articles[0].clauses[0]
        clause.content = "Nội dung quy định đã cập nhật cho sinh viên."
        corpus[0].articles[0].heading = "Phạm vi áp dụng đã cập nhật"
        self.sources[0].write_bytes(self.sources[0].read_bytes() + b"\n# New corpus\n")
        with patch("core.engine.build_corpus", return_value=corpus):
            engine = HocVuEngine.load_or_build(self.config, self.index)
        chunk = next(chunk for chunk in engine.searcher.chunks if clause.content in chunk.text)
        self.assertEqual(chunk.rid, corpus[0].rid)
        self.assertEqual(chunk.aid, corpus[0].articles[0].aid)
        self.assertEqual(chunk.art_heading, corpus[0].articles[0].heading)
        with patch("core.engine.build_index") as build:
            restored = HocVuEngine.load_or_build(self.config, self.index)
        build.assert_not_called()
        self.assertIn(chunk, restored.searcher.chunks)

    def test_chunk_setting_change_rebuilds_once(self):
        HocVuEngine.load_or_build(self.config, self.index)
        changed = replace(self.config, max_chunk_chars=120, overlap_sents=0)
        with patch("core.engine.build_index", wraps=build_index) as build:
            refreshed = HocVuEngine.load_or_build(changed, self.index)
            HocVuEngine.load_or_build(changed, self.index)
        build.assert_called_once()
        expected = HybridSearcher(changed)
        from core.splitter import split_regulation
        expected.build([chunk for regulation in build_corpus(changed.seed)
                        for chunk in split_regulation(regulation, 120, 0)])
        self.assertEqual(refreshed.searcher.chunks, expected.chunks)

    def test_legacy_index_without_fingerprint_rebuilds_once(self):
        searcher = HybridSearcher(self.config)
        searcher.save(self.index, article_version=DocumentRepository.article_build_version())
        with patch("core.engine.build_index", wraps=build_index) as build:
            HocVuEngine.load_or_build(self.config, self.index)
            HocVuEngine.load_or_build(self.config, self.index)
        build.assert_called_once()

    def test_stale_check_runs_before_chunks_or_embeddings_are_built(self):
        for saved in (None, "outdated-fingerprint"):
            with self.subTest(saved=saved):
                searcher = HybridSearcher(self.config)
                searcher.save(self.index, index_fingerprint=saved)
                with patch.object(HybridSearcher, "build") as build:
                    with self.assertRaises(StaleIndexError):
                        HybridSearcher.load(
                            self.index, self.config,
                            index_fingerprint=index_fingerprint(self.config),
                        )
                build.assert_not_called()

    def test_stale_backup_cannot_bypass_freshness_check(self):
        HocVuEngine.load_or_build(self.config, self.index)
        # Saving twice creates a backup with the old fingerprint.
        build_index(self.config, index_path=self.index)
        self.sources[1].write_bytes(self.sources[1].read_bytes() + b"\n# Update\n")
        self.index.write_text("{broken", encoding="utf-8")
        with patch("core.engine.build_index", wraps=build_index) as build:
            HocVuEngine.load_or_build(self.config, self.index)
            HocVuEngine.load_or_build(self.config, self.index)
        build.assert_called_once()

    def test_cli_commands_use_shared_load_or_build_even_if_index_is_missing(self):
        for arguments in (["ask", "Điều kiện bảo lưu?"], ["chat"], ["evaluate"]):
            with self.subTest(command=arguments[0]):
                engine = MagicMock()
                with (
                    patch("sys.argv", ["manage.py", *arguments]),
                    patch("manage.load_config", return_value=self.config),
                    patch("manage.ensure_dirs"),
                    patch("manage.INDEX_JSON", self.index),
                    patch.object(HocVuEngine, "load_or_build", return_value=engine) as load,
                    patch.object(HocVuEngine, "load") as old_load,
                    patch("manage.build_index") as manual_build,
                    patch("builtins.input", return_value="exit"),
                    patch("manage.evaluate", return_value={
                        "grounded_retrieval_accuracy": 1.0,
                        "out_of_scope_refusal_accuracy": 1.0,
                    }) as evaluate,
                    contextlib.redirect_stdout(io.StringIO()),
                ):
                    engine.ask.return_value.confidence = 1.0
                    manage.main()
                load.assert_called_once_with(self.config, self.index)
                old_load.assert_not_called()
                manual_build.assert_not_called()
                if arguments[0] == "evaluate":
                    evaluate.assert_called_once_with(engine, manage.EVAL_JSON)
                elif arguments[0] == "ask":
                    engine.ask.assert_called_once()

    def _writer(self, role, seed, stage="primary", blocked=True):
        context = multiprocessing.get_context("spawn")
        entered, paused, release = (context.Event() for _ in range(3))
        if not blocked:
            release.set()
        process = context.Process(
            target=_rebuild_worker,
            args=(str(self.root), role, seed, entered, paused, release, stage),
        )
        process.start()

        # Spawned children must unpickle every semaphore before the parent
        # drops its references (callers may ignore some returned events).
        def cleanup(events=(entered, paused, release)):
            # A forcibly killed child can leave an Event's internal lock
            # held. Do not touch its synchronization objects after exit.
            if process.is_alive():
                release.set()
            process.join(5)
            if process.is_alive():
                process.terminate()
                process.join(5)

        self.addCleanup(cleanup)
        return process, entered, paused, release

    def _assert_generation(self, path, seed):
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["index_fingerprint"], index_fingerprint(replace(self.config, seed=seed)))
        self.assertEqual(data["article_version"], DocumentRepository.article_build_version())
        restored = HybridSearcher.load(path, self.config)
        self.assertTrue(restored.chunks)
        self.assertEqual([chunk.to_dict() for chunk in restored.chunks], data["chunks"])

    def test_server_startup_and_cli_ingest_overlap_without_losing_either_save(self):
        for existing in (False, True):
            with self.subTest(existing=existing):
                self.index.unlink(missing_ok=True)
                self.index.with_suffix(".json.bak").unlink(missing_ok=True)
                if existing:
                    build_index(self.config, index_path=self.index)
                server, _, paused, release = self._writer("server", 11)
                self.assertTrue(paused.wait(15), "Server never reached the commit boundary")
                cli, entered, _, _ = self._writer("cli", 22, blocked=False)
                self.assertTrue(entered.wait(15), "CLI never reached save while server was paused")
                # No timing sleeps: both processes are in save before releasing.
                release.set()
                for process in (server, cli):
                    process.join(20)
                    self.assertEqual(process.exitcode, 0)
                self._assert_generation(self.index, 22)
                self._assert_generation(self.index.with_suffix(".json.bak"), 11)
                self.assertFalse(list(self.index.parent.glob("*.tmp")))

    def test_killed_writer_preserves_committed_files_and_releases_lock(self):
        for stage in ("backup", "primary", "committed"):
            with self.subTest(stage=stage):
                build_index(self.config, index_path=self.index)
                build_index(replace(self.config, seed=33), index_path=self.index)
                process, _, paused, _ = self._writer("server", 11, stage=stage)
                self.assertTrue(paused.wait(15), f"Writer never reached {stage}")
                process.terminate()
                process.join(10)
                self.assertIsNotNone(process.exitcode)
                self._assert_generation(self.index, 11 if stage == "committed" else 33)
                self._assert_generation(
                    self.index.with_suffix(".json.bak"),
                    self.config.seed if stage == "backup" else 33,
                )
                # A killed process must not leave a permanently held lock.
                cli, _, _, _ = self._writer("cli", 22, blocked=False)
                cli.join(20)
                self.assertEqual(cli.exitcode, 0)
                self._assert_generation(self.index, 22)

    def test_failed_replace_keeps_primary_and_valid_backup_and_cleans_temps(self):
        from core.index_storage import atomic_write

        for stage in ("backup", "primary"):
            with self.subTest(stage=stage):
                build_index(self.config, index_path=self.index)
                build_index(self.config, index_path=self.index)
                before = self.index.read_bytes()
                target = self.index.with_suffix(".json.bak") if stage == "backup" else self.index
                original_replace = os.replace

                def fail_replace(source, destination):
                    if Path(destination) == target:
                        raise OSError("Injected interrupted commit")
                    return original_replace(source, destination)

                with patch("core.index_storage.os.replace", side_effect=fail_replace):
                    with self.assertRaisesRegex(OSError, "Injected"):
                        build_index(replace(self.config, seed=11), index_path=self.index)
                self.assertEqual(self.index.read_bytes(), before)
                self._assert_generation(self.index.with_suffix(".json.bak"), self.config.seed)
                self.assertFalse(list(self.index.parent.glob("*.tmp")))
        # The same cleanup applies if a flush fails before publication.
        with patch("core.index_storage.os.fsync", side_effect=OSError("Injected flush failure")):
            with self.assertRaisesRegex(OSError, "flush failure"):
                atomic_write(self.index, b"not committed")
        self.assertEqual(self.index.read_bytes(), before)
        self.assertFalse(list(self.index.parent.glob("*.tmp")))

    def test_rebuild_does_not_replace_good_backup_with_corrupt_primary(self):
        build_index(self.config, index_path=self.index)
        build_index(self.config, index_path=self.index)
        backup = self.index.with_suffix(".json.bak")
        good_backup = backup.read_bytes()
        for corrupt in ("{broken", "[]", '{"chunks": [] , "schema_version": 999}',
                        '{"chunks": [{}]}', '{"chunks": "not a list"}'):
            with self.subTest(corrupt=corrupt):
                self.index.write_text(corrupt, encoding="utf-8")
                build_index(replace(self.config, seed=11), index_path=self.index)
                self.assertEqual(backup.read_bytes(), good_backup)
                self._assert_generation(self.index, 11)


if __name__ == "__main__":
    unittest.main()
