"""Precomputation must preserve Vietnamese evidence and index lifecycle rules."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, replace
import gc
import json
from pathlib import Path
import tempfile
import unicodedata
import unittest
from unittest.mock import patch
import weakref

from core.generator import Generator
from core.models import Chunk, RankedChunk
from core.nlp import ACADEMIC_TOKEN_ALIASES, accent_key, accented_content_tokens, content_tokens, has_diacritics, strip_accents
from core.searcher import HybridSearcher
from core.settings import AppConfig


def chunk(text="ĐRL tối thiểu 65 điểm để xét học bổng.", **changes):
    return Chunk(**{
        "cid": "synthetic", "rid": "UPL-SYNTHETIC", "reg_title": "Quy chế học bổng",
        "version": "2026", "valid_from": "2020-01-01", "valid_until": None,
        "aid": "Điều 1", "art_heading": "Điều kiện xét học bổng",
        "clause_ids": ["1"], "text": text, **changes,
    })


class SearcherFeatureTests(unittest.TestCase):
    def setUp(self):
        self.config = AppConfig(semantic_enabled=False)
        self.searcher = HybridSearcher(self.config)

    def test_precomputed_sets_exactly_match_the_original_formulas(self):
        for text in (
            "ĐRL tối thiểu 65 điểm để xét HBKKHT.",
            "Bảo lưu kết quả học tập trong hai học kỳ.",
            "Học bổng tối đa 700000 đồng; không có thông tin bóng đá.",
            unicodedata.normalize("NFD", "Hoà nhập, hòa nhập và hỗ trợ học tập."),
            "",
        ):
            with self.subTest(text=text):
                item = chunk(text)
                self.searcher.build([item])
                features = self.searcher._features[0]
                evidence = HybridSearcher._evidence_text(item)
                tokens = accented_content_tokens(evidence, expand_aliases=False)
                aliases = set()
                for token in tokens:
                    expansion = ACADEMIC_TOKEN_ALIASES.get(strip_accents(token))
                    if expansion:
                        aliases |= HybridSearcher._phrase_index(list(expansion))
                self.assertEqual(features.heading_forms, set(HybridSearcher._index_forms(
                    accented_content_tokens(f"{item.version} {item.reg_title} {item.art_heading}"),
                )))
                self.assertEqual(features.normalized_text, " ".join(content_tokens(item.text)))
                self.assertEqual(features.evidence_words, set(HybridSearcher._index_forms(tokens)))
                self.assertEqual(features.evidence_pairs, HybridSearcher._phrase_index(tokens) |
                                 HybridSearcher._phrase_index(HybridSearcher._raw_words(evidence)))
                self.assertEqual(features.alias_pairs, aliases)
                self.assertEqual(features.ranking_pairs, HybridSearcher._phrase_index(accented_content_tokens(evidence)))
                self.assertEqual(features.body_lower, HybridSearcher._clause_body(item).lower())
                self.assertEqual(features.body_ascii, strip_accents(HybridSearcher._clause_body(item)).lower())

    def test_warmed_retrieval_and_generator_never_rebuild_document_features(self):
        item = chunk("Điều kiện bảo lưu kết quả học tập: nộp hồ sơ tại phòng đào tạo.",
                     art_heading="Bảo lưu")
        self.searcher.build([item])
        features = self.searcher._features[0]
        query = "Điều kiện bảo lưu kết quả học tập"
        with (
            patch.object(HybridSearcher, "_index_forms", side_effect=AssertionError("reindexed words")),
            patch.object(HybridSearcher, "_phrase_index", side_effect=AssertionError("reindexed phrases")),
            patch.object(HybridSearcher, "_evidence_text", side_effect=AssertionError("rebuilt evidence")),
        ):
            hits = self.searcher.rerank_by_coverage(query, self.searcher.search(query, 20, "2026-10-20"))
            self.assertGreater(self.searcher.lexical_coverage(query, hits), 0)
            self.assertTrue(self.searcher.has_specific_evidence(query, hits))
            answer, references = Generator(self.config).generate(query, hits)
            self.assertTrue(references)
            self.assertIn("nộp hồ sơ", answer)
            self.assertIs(HybridSearcher._chunk_features(item), features)

    def test_lazy_classmethod_callers_reuse_immutable_features_without_build(self):
        item = chunk()
        self.assertFalse(hasattr(item, "_retrieval_features"))
        HybridSearcher._evidence_support("điểm rèn luyện", item)
        features = HybridSearcher._chunk_features(item)
        self.assertIs(HybridSearcher._chunk_features(item), features)
        self.assertIsInstance(features.evidence_words, frozenset)
        self.assertIsInstance(features.evidence_pairs, frozenset)
        with self.assertRaises(FrozenInstanceError):
            features.normalized_text = "changed"
        self.assertEqual(self.searcher.chunks, [])

    def test_alias_ranking_does_not_turn_into_single_word_evidence(self):
        hit = RankedChunk(chunk=chunk("ĐRL tốt.", art_heading="Xếp loại"), score=1)
        self.assertEqual(HybridSearcher.lexical_coverage("điểm danh", hit), 0)
        self.assertEqual(HybridSearcher.lexical_coverage("điểm rèn luyện", hit), 1)
        self.assertEqual(HybridSearcher.lexical_coverage("diem ren luyen", hit), 1)
        self.assertGreater(HybridSearcher.phrase_coverage("điểm rèn luyện", hit), 0)
        self.assertFalse(HybridSearcher.has_specific_evidence("điểm danh", [hit]))

    def test_raw_stopword_adjacency_is_preserved_for_unaccented_anchors(self):
        item = chunk("Bảo lưu kết quả.", art_heading="")
        _, anchors = HybridSearcher._evidence_support("bao luu", item)
        self.assertIn(HybridSearcher._query_form("luu"), anchors)

    def test_same_cid_never_shares_different_documents_evidence(self):
        first = chunk("Học bổng tối đa 700000 đồng.", art_heading="")
        second = replace(first, text="Giải bóng đá tổ chức vào tháng 10.")
        self.searcher.build([first, second])
        self.assertIsNot(*self.searcher._features)
        hits = [RankedChunk(chunk=item, score=1) for item in (first, second)]
        self.assertEqual(HybridSearcher.lexical_coverage("bóng đá", hits[0]), 0)
        self.assertEqual(HybridSearcher.lexical_coverage("bóng đá", hits[1]), 1)
        self.assertFalse(HybridSearcher.has_specific_evidence("giai bong da", [hits[0]]))
        self.assertTrue(HybridSearcher.has_specific_evidence("giai bong da", [hits[1]]))

    def test_standalone_features_refresh_after_text_or_heading_changes(self):
        item = chunk("Học bổng dành cho sinh viên.", art_heading="")
        original = HybridSearcher._chunk_features(item)
        item.text = "Ký túc xá có wifi miễn phí."
        current = HybridSearcher._chunk_features(item)
        self.assertIsNot(current, original)
        self.assertTrue(HybridSearcher.has_specific_evidence(
            "Ký túc xá có wifi không?", [RankedChunk(item, 1)],
        ))
        item.art_heading = "Điều kiện bảo lưu"
        self.assertIsNot(HybridSearcher._chunk_features(item), current)

    def test_rebuild_replaces_feature_order_and_handles_empty_corpus(self):
        first, second = chunk(), chunk("Sinh viên bảo lưu tối đa hai học kỳ.", cid="second")
        self.searcher.build([first, second])
        previous = self.searcher._features[:]
        self.searcher.build([second, first])
        self.assertEqual(self.searcher._features, list(reversed(previous)))
        second.text = "Thực tập tốt nghiệp cần đủ 135 tín chỉ."
        self.searcher.build([second])
        self.assertIsNot(self.searcher._features[0], previous[1])
        self.assertIn("135", self.searcher._features[0].normalized_text)
        self.searcher.build([])
        self.assertEqual(self.searcher._features, [])
        self.assertEqual(self.searcher.search("bảo lưu"), [])

    def test_features_are_not_serialized_and_load_precomputes_them_again(self):
        item = chunk()
        original = item.to_dict()
        self.searcher.build([item])
        self.assertEqual(item.to_dict(), original)
        self.assertEqual(RankedChunk(item, 1).to_dict()["chunk"], original)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "index.json"
            self.searcher.save(str(path))
            self.assertEqual(json.loads(path.read_text())["chunks"], [original])
            loaded = HybridSearcher.load(str(path), self.config)
        self.assertEqual(loaded._features, self.searcher._features)
        self.assertIsNot(loaded._features[0], self.searcher._features[0])
        self.assertEqual(
            [hit.to_dict() for hit in loaded.search("học bổng", 20)],
            [hit.to_dict() for hit in self.searcher.search("học bổng", 20)],
        )

    def test_no_global_cache_retains_removed_documents(self):
        item = chunk()
        reference = weakref.ref(item)
        self.searcher.build([item])
        del item
        self.searcher.build([])
        gc.collect()
        self.assertIsNone(reference())

    def test_subclasses_do_not_reuse_a_different_evidence_definition(self):
        class AlternateEvidence(HybridSearcher):
            @classmethod
            def _evidence_text(cls, item):
                return "Wifi ký túc xá miễn phí."
        item = chunk("Nội dung không liên quan.", art_heading="")
        parent = HybridSearcher._chunk_features(item)
        other = AlternateEvidence._chunk_features(item)
        self.assertNotEqual(parent.evidence_words, other.evidence_words)
        self.assertEqual(HybridSearcher._chunk_features(item), parent)

    def test_concurrent_standalone_reads_only_publish_complete_features(self):
        item = chunk()
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: HybridSearcher._evidence_support("diem ren luyen", item), range(32)))
        self.assertTrue(all(result == results[0] for result in results))
        self.assertTrue(results[0][0])
        self.assertTrue(results[0][1])

    def test_non_specific_constants_preserve_all_old_membership_rules(self):
        words = HybridSearcher._generic_institutional_words + HybridSearcher._conversational_words
        for term in (*words, *(strip_accents(word) for word in words), "đá", "đa", "da", "wifi", "bóng", "bổng"):
            expected = (
                accent_key(term) in {accent_key(word) for word in words}
                if has_diacritics(term)
                else term not in HybridSearcher._ambiguous_unaccented and term in {strip_accents(word) for word in words}
            )
            self.assertEqual(HybridSearcher._is_non_specific(term), expected, term)
