import unittest

from core.classifier import Classifier, Intent
from core.corpus import build_corpus
from core.generator import Generator
from core.searcher import HybridSearcher
from core.scenarios import expand_retrieval_query, is_attendance_training_scenario
from core.settings import AppConfig
from core.splitter import split_regulation


class RagPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = AppConfig(max_units=2, semantic_enabled=False)
        chunks = [chunk for regulation in build_corpus() for chunk in split_regulation(regulation, 800, 1)]
        cls.searcher = HybridSearcher(cls.config)
        cls.searcher.build(chunks)

    def test_retrieves_a_grounded_bao_luu_clause(self):
        hits = self.searcher.search("Điều kiện bảo lưu kết quả học tập", 3, "2026-10-04")
        self.assertTrue(hits)
        self.assertEqual(hits[0].chunk.aid, "Điều 5")
        self.assertIn("Bảo lưu", hits[0].chunk.art_heading)

    def test_filters_expired_regulations_for_current_query(self):
        hits = self.searcher.search("Quy định cũ có cho phép thi lại không", 10, "2026-10-04")
        self.assertTrue(all(hit.chunk.valid_until != "2026-08-31" for hit in hits))

    def test_blocks_non_academic_question(self):
        self.assertEqual(Classifier().classify("Căng tin trường có món gì?"), Intent.OUT_OF_SCOPE)

    def test_admits_administrative_document_question_but_blocks_casual_question(self):
        classifier = Classifier()
        self.assertEqual(classifier.classify("Tại sao một con vịt lại sinh ra một con gà?"), Intent.OUT_OF_SCOPE)
        self.assertEqual(classifier.classify("Thời hạn cung cấp thông tin là khi nào?"), Intent.ACADEMIC_RULES)

    def test_explains_absence_and_training_as_a_grounded_condition(self):
        question = "Tôi nghỉ 3 tiết học thì điểm rèn luyện bị ảnh hưởng như nào?"
        self.assertTrue(is_attendance_training_scenario(question))
        hits = self.searcher.search(expand_retrieval_query(question), 8, "2026-10-05")
        result = Generator(self.config).generate_attendance_training_scenario(hits)
        self.assertIsNotNone(result)
        answer, references = result
        self.assertIn("không quy định mức trừ", answer)
        self.assertIn("25%", answer)
        self.assertGreaterEqual(len(references), 2)


if __name__ == "__main__":
    unittest.main()
