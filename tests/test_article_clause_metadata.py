from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.documents import DocumentRepository
from core.generator import Generator
from core.models import RankedChunk
from core.splitter import split_regulation


class ArticleClauseMetadataTests(unittest.TestCase):
    def test_common_locators_create_real_article_and_clause_ids(self):
        text = "## Điều kiện bảo lưu\nSinh viên được bảo lưu tối đa bốn học kỳ."
        for locator in ("Điều 4, Khoản 2", "điều 4 khoản 2", "Khoản 2, Điều 4", "Điều4 / Khoản2"):
            with self.subTest(locator=locator):
                articles = DocumentRepository._make_articles(text, "Quy định bảo lưu", locator)
                self.assertEqual(len(articles), 1)
                self.assertEqual(articles[0].aid, "Điều 4")
                self.assertEqual(articles[0].heading, "Điều kiện bảo lưu")
                self.assertEqual([clause.cid for clause in articles[0].clauses], ["2"])
                self.assertIn("bốn học kỳ", articles[0].clauses[0].content)

    def test_document_locator_covers_all_sections_without_inventing_new_legal_clause_numbers(self):
        text = "## Điều kiện\nSinh viên phải nộp đơn.\n## Thời gian\nĐược bảo lưu tối đa bốn học kỳ."
        article = DocumentRepository._make_articles(text, "Bảo lưu", "Điều 4, Khoản 2")[0]
        self.assertEqual(article.aid, "Điều 4")
        self.assertEqual([clause.cid for clause in article.clauses], ["2"])
        for section in ("Điều kiện", "nộp đơn", "Thời gian", "bốn học kỳ"):
            self.assertIn(section, article.clauses[0].content)

    def test_article_only_and_clause_only_are_honored(self):
        text = "## Điều kiện bảo lưu\nSinh viên được bảo lưu theo quy định."
        article = DocumentRepository._make_articles(text, "Bảo lưu", "Điều 7a")[0]
        self.assertEqual(article.aid, "Điều 7a")
        article = DocumentRepository._make_articles(text, "Bảo lưu", "Khoản 3b")[0]
        self.assertEqual(article.aid, "Nội dung")
        self.assertEqual(article.clauses[0].cid, "3b")

    def test_free_form_and_multi_article_locators_are_preserved_not_partially_parsed(self):
        for locator in ("Phụ lục II", "Điều 4, Điều 5", "Điều 4, Khoản 1 và 2"):
            with self.subTest(locator=locator):
                article = DocumentRepository._make_articles("Nội dung quy định còn nguyên.", "Quy định", locator)[0]
                self.assertEqual(article.aid, locator)
                self.assertIn("còn nguyên", article.clauses[0].content)

    def test_empty_locator_keeps_existing_auto_sections(self):
        text = "## Điều kiện\nNội dung thứ nhất.\n## Thời gian\nNội dung thứ hai."
        articles = DocumentRepository._make_articles(text, "Bảo lưu", "")
        self.assertEqual([article.aid for article in articles], ["Mục 1", "Mục 2"])
        self.assertEqual([article.heading for article in articles], ["Điều kiện", "Thời gian"])

    def test_upload_locator_survives_manifest_reload_chunking_and_answer_references(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = DocumentRepository(Path(directory))
            text = "## Điều kiện bảo lưu\n" + "Sinh viên được bảo lưu tối đa bốn học kỳ. " * 80
            with patch.object(repository, "extract", return_value=(text, 1)):
                entry = repository.add(
                    "bao_luu.pdf", b"%PDF-1.7 synthetic locator",
                    metadata={"article_clause": "Điều 4, Khoản 2", "document_date": "2020-01-01"},
                )
            repository = DocumentRepository(Path(directory))
            regulation = repository.regulations()[0]
            chunks = split_regulation(regulation, max_chars=200, overlap_sents=1)
            self.assertGreater(len(chunks), 2)
            self.assertEqual(entry["article_clause"], "Điều 4, Khoản 2")
            for chunk in chunks:
                self.assertEqual(chunk.aid, "Điều 4")
                self.assertEqual(chunk.clause_ids, ["2"])
                reference = Generator._reference(RankedChunk(chunk, score=1.0))
                self.assertEqual(reference.to_dict()["aid"], "Điều 4")
                self.assertEqual(reference.to_dict()["clause_ids"], ["2"])
            self.assertEqual(repository.get_text(entry["id"])["text"], text)
