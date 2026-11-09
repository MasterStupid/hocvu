"""Serialization must preserve the complete scored retrieval, not null entries."""
import json
import unittest

from core.models import Chunk, RankedChunk, Response


class RetrievalSerializationTests(unittest.TestCase):
    def setUp(self):
        self.chunk_data = {
            "cid": "test-chunk", "rid": "test-regulation",
            "reg_title": "Quy chế thử nghiệm", "version": "2026",
            "valid_from": "2026-01-01", "valid_until": None,
            "aid": "Điều 2", "art_heading": "Điểm rèn luyện",
            "clause_ids": ["3"], "text": "Trừ 5 điểm/lần.", "seq": 1,
        }
        self.ranked = RankedChunk(
            chunk=Chunk(**self.chunk_data),
            score=0.123456, bm25=12.345678, vec=0.876543,
        )
        self.expected = {
            "chunk": self.chunk_data, "score": 0.12346,
            "bm25": 12.34568, "vec": 0.87654, "cite": "Điều 2, K.3",
        }

    def test_ranked_chunk_returns_full_dictionary_with_rounded_scores(self):
        self.assertEqual(self.ranked.to_dict(), self.expected)
        self.assertEqual(self.ranked.to_dict(include_retrieved=True), self.expected)

    def test_response_preserves_each_retrieved_entry_and_its_order(self):
        second = RankedChunk(chunk=Chunk(**{**self.chunk_data, "cid": "second"}),
                             score=0.5, bm25=0.0, vec=0.0)
        response = Response(query="q", answer="a", retrieved=[self.ranked, second])
        result = response.to_dict(include_retrieved=True)
        self.assertEqual(result["retrieved"], [
            self.expected,
            {
                "chunk": {**self.chunk_data, "cid": "second"},
                "score": 0.5, "bm25": 0.0, "vec": 0.0, "cite": "Điều 2, K.3",
            },
        ])
        self.assertEqual(json.loads(json.dumps(result, ensure_ascii=False)), result)

    def test_raw_retrieval_remains_opt_in(self):
        response = Response(query="q", answer="a", retrieved=[self.ranked])
        self.assertNotIn("retrieved", response.to_dict())
        self.assertEqual(response.to_dict(include_retrieved=True)["retrieved"], [self.expected])
        # Enabling debug serialization must not change later public responses.
        self.assertNotIn("retrieved", response.to_dict())

    def test_empty_debug_retrieval_is_an_empty_list(self):
        self.assertEqual(
            Response(query="q", answer="a").to_dict(include_retrieved=True)["retrieved"],
            [],
        )
