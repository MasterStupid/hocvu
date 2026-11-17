from dataclasses import replace
import re
import unittest

from core.models import Article, Clause, Regulation
from core.splitter import _gen_chunk_id, split_regulation


def regulation(content, heading="Học bổng", rid="REG", aid="Điều 2"):
    return Regulation(
        rid=rid, title="Quy định", category="Học vụ", version="2026",
        valid_from="2020-01-01", valid_until=None, issuer="Trường",
        articles=[Article(aid, heading, [Clause("1", content)])],
    )


class ChunkBoundsTests(unittest.TestCase):
    def body(self, chunk):
        return chunk.text.removeprefix(chunk.art_heading + "\n")

    def test_long_sentence_and_unbroken_tokens_respect_the_hard_limit_without_loss(self):
        for content in ("Điều kiện học bổng xuất sắc " * 50, "ắ" * 1000):
            source = regulation(content)
            for limit in (1, 2, 9, 10, 80, 800):
                with self.subTest(limit=limit, content=content[:10]):
                    chunks = split_regulation(source, limit, 0)
                    self.assertTrue(chunks)
                    self.assertTrue(all(0 < len(chunk.text) <= limit for chunk in chunks))
                    reconstructed = "".join(self.body(chunk) for chunk in chunks)
                    self.assertEqual(re.sub(r"\s+", "", reconstructed), re.sub(r"\s+", "", content))

    def test_large_overlap_drops_oldest_sentences_until_the_next_fits(self):
        source = regulation("Một câu ngắn. Hai câu ngắn. Ba câu ngắn. Bốn câu ngắn. Năm câu ngắn.")
        chunks = split_regulation(source, 38, 100000)
        self.assertTrue(all(len(chunk.text) <= 38 for chunk in chunks))
        self.assertGreater(len(chunks), 1)
        for sentence in source.articles[0].clauses[0].content.split("."):
            if sentence.strip():
                self.assertTrue(any(sentence.strip() in self.body(chunk) for chunk in chunks))

    def test_overlap_is_preserved_when_it_fits(self):
        chunks = split_regulation(regulation("Một. Hai. Ba. Bốn. Năm.", heading="H"), 16, 1)
        self.assertEqual([self.body(chunk) for chunk in chunks], ["Một. Hai. Ba.", "Ba. Bốn. Năm."])

    def test_long_headings_remain_complete_in_metadata_without_displacing_body(self):
        heading = "Tiêu đề dài " * 100
        chunks = split_regulation(regulation("Nội dung cần giữ nguyên.", heading), 8, 0)
        self.assertTrue(all(chunk.art_heading == heading for chunk in chunks))
        self.assertTrue(all(len(chunk.text) <= 8 for chunk in chunks))
        self.assertEqual("".join(self.body(chunk) for chunk in chunks).replace(" ", ""), "Nộidungcầngiữnguyên.")

    def test_direct_call_rejects_invalid_limits(self):
        for limit, overlap in ((0, 1), (-1, 0), (800, -1)):
            with self.assertRaises(ValueError):
                split_regulation(regulation("Nội dung."), limit, overlap)

    def test_identical_content_has_distinct_ids_per_regulation_and_article(self):
        first = regulation("Nội dung giống nhau.")
        second = replace(first, rid="OTHER")
        third = regulation("Nội dung giống nhau.", aid="Điều 3")
        chunks = [split_regulation(item, 800, 1)[0] for item in (first, second, third)]
        self.assertEqual(len({chunk.cid for chunk in chunks}), 3)
        self.assertEqual(chunks[0].cid, split_regulation(first, 800, 1)[0].cid)
        self.assertNotEqual(_gen_chunk_id("a_b", "c", "text", 1), _gen_chunk_id("a", "b_c", "text", 1))

    def test_split_and_repeated_clauses_have_distinct_stable_ids(self):
        source = regulation("Câu dài. " * 30)
        source.articles[0].clauses.append(Clause("2", source.articles[0].clauses[0].content))
        chunks = split_regulation(source, 40, 2)
        self.assertEqual(len(chunks), len({chunk.cid for chunk in chunks}))
        self.assertEqual([chunk.cid for chunk in chunks], [chunk.cid for chunk in split_regulation(source, 40, 2)])
