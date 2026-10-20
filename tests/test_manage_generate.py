import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from core.corpus import build_corpus, build_markdown, build_qa
from core.settings import AppConfig, ROOT
import manage


class GenerateCommandTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.raw = self.root / "raw"
        self.config = AppConfig(seed=17, semantic_enabled=True)

    def run_cli(self, *arguments):
        environment = {
            **os.environ,
            "HV_DATA_DIR": str(self.root), "HV_SEED": str(self.config.seed),
            # Generation must work even when semantic retrieval is configured.
            "HV_SEMANTIC": "1", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
            "HV_LLM": "local", "OPENAI_API_KEY": "", "GEMINI_API_KEY": "",
            "HV_API_TOKEN": "synthetic-generate-test", "SESSION_SECRET": "synthetic-generate-test",
        }
        return subprocess.run(
            [sys.executable, str(ROOT / "manage.py"), *arguments], cwd=ROOT,
            env=environment, capture_output=True, text=True, encoding="utf-8", timeout=30,
        )

    def test_real_command_exports_complete_utf8_corpus_markdown_and_qa(self):
        result = self.run_cli("generate")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("Not implemented", result.stdout)
        summary = json.loads(result.stdout)
        corpus = build_corpus(self.config.seed)
        questions = build_qa(corpus, self.config.seed)
        self.assertEqual(summary["seed"], self.config.seed)
        self.assertEqual(summary["documents"], len(corpus))
        self.assertEqual(summary["articles"], sum(len(item.articles) for item in corpus))
        self.assertEqual(summary["questions"], len(questions))
        self.assertEqual(
            {Path(name) for name in summary["files"]},
            {self.raw / name for name in ("corpus.json", "corpus.md", "qa_testset.json")},
        )
        self.assertEqual(
            json.loads((self.raw / "corpus.json").read_text(encoding="utf-8")),
            [item.to_dict() for item in corpus],
        )
        self.assertEqual(
            json.loads((self.raw / "qa_testset.json").read_text(encoding="utf-8")),
            [item.to_dict() for item in questions],
        )
        markdown = (self.raw / "corpus.md").read_text(encoding="utf-8")
        self.assertEqual(markdown, build_markdown(corpus) + "\n")
        self.assertIn("\n### ", markdown)
        self.assertIn("học", markdown.lower())
        self.assertEqual({path.name for path in self.root.iterdir()}, {"raw"})

    def test_repeat_command_is_deterministic_and_preserves_all_user_stores(self):
        preserved = {
            "documents/manifest.json": b'{"synthetic":"keep unchanged"}',
            "documents/uploads/original.pdf": b"synthetic upload",
            "sessions.db": b"do not open this synthetic database",
            "index/index.json": b"do not load this synthetic index",
            "models/keep": b"do not download models",
            "raw/unrelated.txt": b"keep unrelated raw data",
        }
        for name, content in preserved.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        first = self.run_cli("generate")
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        exports = {name: (self.raw / name).read_bytes() for name in ("corpus.json", "corpus.md", "qa_testset.json")}
        second = self.run_cli("generate")
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(first.stdout, second.stdout)
        for name, expected in exports.items():
            self.assertEqual((self.raw / name).read_bytes(), expected)
        for name, expected in preserved.items():
            self.assertEqual((self.root / name).read_bytes(), expected, name)
        self.assertEqual(list((self.root / "models").iterdir()), [self.root / "models" / "keep"])

    def test_generation_does_not_load_models_or_call_network(self):
        with (
            patch("core.searcher.SemanticEncoder") as model,
            patch("urllib.request.urlopen") as network,
            patch.object(manage.HocVuEngine, "load_or_build") as engine,
        ):
            manage.generate_demo_data(self.config, self.raw)
        model.assert_not_called()
        network.assert_not_called()
        engine.assert_not_called()

    def test_failed_write_returns_nonzero_without_a_success_summary(self):
        output, errors = io.StringIO(), io.StringIO()
        with (
            patch.object(sys, "argv", ["manage.py", "generate"]),
            patch.object(manage, "RAW", self.raw),
            patch.object(manage, "load_config", return_value=self.config),
            patch.object(manage, "atomic_write", side_effect=OSError("synthetic disk failure")),
            contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors),
        ):
            with self.assertRaises(SystemExit) as raised:
                manage.main()
        self.assertEqual(raised.exception.code, 1)
        self.assertEqual(output.getvalue(), "")
        self.assertIn("Không thể xuất dữ liệu mẫu", errors.getvalue())

    def test_serialization_finishes_before_replacing_any_export(self):
        self.raw.mkdir()
        original = self.raw / "corpus.json"
        original.write_bytes(b"original demo export")
        with patch.object(manage, "build_qa", side_effect=ValueError("synthetic build failure")):
            with self.assertRaises(ValueError):
                manage.generate_demo_data(self.config, self.raw)
        self.assertEqual(original.read_bytes(), b"original demo export")
