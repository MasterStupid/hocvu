from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from core.corpus import build_corpus, build_markdown
from core.models import Article, Clause, Regulation
from core.searcher import HybridSearcher
from core.semantic import SemanticEncoder
from core.settings import AppConfig
from core.splitter import split_regulation


def regulation(content="Sinh viên được cấp học bổng theo kết quả học tập."):
    return Regulation(
        rid="TEST", title="Quy định học bổng", category="Học bổng", version="2026",
        valid_from="2020-01-01", valid_until=None, issuer="Trường",
        articles=[Article("Điều 4", "Học bổng", [Clause("2", content)])],
    )


class EmbeddingPassageTests(unittest.TestCase):
    def passages(self, chunks):
        encoder = MagicMock(cache_error="", error="")
        encoder.build.return_value = True
        with patch("core.searcher.SemanticEncoder", return_value=encoder):
            HybridSearcher(AppConfig(semantic_enabled=True)).build(chunks)
        return encoder.build.call_args.args[0]

    def test_heading_is_embedded_once_for_every_splitter_chunk(self):
        chunks = split_regulation(regulation("Sinh viên được hỗ trợ học tập. " * 30), 120, 1)
        self.assertGreater(len(chunks), 1)
        self.assertEqual(self.passages(chunks), [chunk.text for chunk in chunks])

    def test_a_heading_phrase_in_the_body_is_preserved(self):
        chunks = split_regulation(regulation("Học bổng được cấp cho sinh viên."), 800, 0)
        self.assertEqual(self.passages(chunks), ["Học bổng\nHọc bổng được cấp cho sinh viên."])

    def test_legacy_body_without_prefix_still_gets_one_heading(self):
        chunk = split_regulation(regulation(), 800, 0)[0]
        legacy = replace(chunk, text="Nội dung chưa có tiêu đề ở đầu.")
        self.assertEqual(self.passages([legacy]), ["Học bổng\nNội dung chưa có tiêu đề ở đầu."])

    def test_fixed_passages_do_not_reuse_the_old_duplicate_heading_vector_cache(self):
        chunks = split_regulation(regulation(), 800, 0)
        old = [f"{chunk.art_heading}\n{chunk.text}" for chunk in chunks]
        new = self.passages(chunks)
        with tempfile.TemporaryDirectory() as directory:
            encoder = SemanticEncoder("synthetic-model", Path(directory))
            self.assertNotEqual(encoder._cache_key(old, "same-source"), encoder._cache_key(new, "same-source"))


class MarkdownOutputTests(unittest.TestCase):
    def test_markdown_has_real_line_breaks_and_standalone_headers(self):
        output = build_markdown([regulation()])
        lines = output.splitlines()
        self.assertGreater(len(lines), 10)
        self.assertIn("### Điều 4: Học bổng", lines)
        self.assertIn("Khoản 2. Sinh viên được cấp học bổng theo kết quả học tập.", lines)
        self.assertIn("---", lines)
        self.assertNotIn("\\n", output)

    def test_export_keeps_literal_backslash_n_inside_source_content(self):
        output = build_markdown([regulation(r"Ví dụ ký tự \n phải giữ nguyên.")])
        self.assertIn("Khoản 2. Ví dụ ký tự \\n phải giữ nguyên.\n", output)
        self.assertGreater(len(output.splitlines()), 10)

    def test_whole_corpus_exports_separate_regulations_and_unicode(self):
        corpus = build_corpus()
        output = build_markdown(corpus)
        self.assertGreater(len(output.splitlines()), len(corpus) * 10)
        for item in corpus:
            self.assertIn(item.title, output)
            for article in item.articles:
                self.assertIn(f"### {article.aid}: {article.heading}", output.splitlines())
