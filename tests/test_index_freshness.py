"""Automatic index refresh must behave the same for the server and CLI."""
import contextlib
import io
import json
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


class IndexFreshnessTests(unittest.TestCase):
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
            patch("core.engine.AUD", self.root / "audio"),
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


if __name__ == "__main__":
    unittest.main()
