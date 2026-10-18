import unittest
import io
import json
import tempfile
import zipfile
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch
from xml.sax.saxutils import escape

from core.classifier import Classifier, Intent
from core.corpus import build_corpus, build_qa
from core.evaluation import evaluate
from core.generator import Generator
from core.searcher import HybridSearcher
from core.scenarios import expand_retrieval_query, is_attendance_training_scenario
from core.settings import AppConfig
from core.engine import HocVuEngine, build_index
from core.index_version import index_fingerprint
from core.models import Reference, Response
from core.nlp import accent_key, content_tokens
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

    def test_evaluation_rejects_wrong_articles_in_expected_regulation(self):
        questions = build_qa(build_corpus())
        cases = {
            "Điểm TOEIC tối thiểu để học tiếng Anh chuyên ngành là bao nhiêu?": "Điều 2",
            "Nghỉ học bao nhiêu phần trăm thì bị cấm thi?": "Điều 3",
            "Sinh viên được bảo lưu tối đa bao nhiêu học kỳ?": "Điều 5",
        }
        for question, expected_aid in cases.items():
            item = next(item for item in questions if item.question == question)
            self.assertEqual(item.source_aids, [expected_aid])
            expected_ref = Reference(
                rid=item.source_rids[0], reg_title="", aid=expected_aid,
                art_heading="", clause_ids=[], excerpt="",
            )
            wrong_article = replace(expected_ref, aid="Điều 8")
            wrong_regulation = replace(expected_ref, rid="unrelated-regulation")
            scenarios = [
                ("correct", [expected_ref], False, True, True),
                ("wrong article", [wrong_article], False, True, False),
                ("wrong regulation", [wrong_regulation], False, False, False),
                ("split match", [wrong_article, wrong_regulation], False, True, False),
                ("no references", [], False, False, False),
                ("refused with citation", [expected_ref], True, False, False),
                ("support plus distractor", [wrong_article, expected_ref], False, True, True),
            ]
            for name, references, refused, legacy, article in scenarios:
                with self.subTest(question=question, scenario=name), tempfile.TemporaryDirectory() as tmp:
                    engine = MagicMock(config=self.config)
                    engine.ask.return_value = Response(
                        query=question, answer="", references=references, refused=refused,
                    )
                    path = Path(tmp) / "report.json"
                    with patch("core.evaluation.build_qa", return_value=[item]):
                        report = evaluate(engine, path)
                    row = report["rows"][0]
                    self.assertEqual(row["correct"], legacy)
                    self.assertEqual(row["article_correct"], article)
                    self.assertEqual(row["expected_aids"], [expected_aid])
                    self.assertEqual(row["cited_articles"], [
                        {"rid": rid, "aid": aid}
                        for rid, aid in sorted({(ref.rid, ref.aid) for ref in references})
                    ])
                    self.assertEqual(report["grounded_retrieval_accuracy"], float(legacy))
                    self.assertEqual(report["article_grounded_retrieval_accuracy"], float(article))
                    self.assertEqual(report["article_grounded_retrieval_total"], 1)
                    self.assertEqual(json.loads(path.read_text(encoding="utf-8")), report)
                    engine.ask.assert_called_once_with(
                        question, session_id=f"evaluation-{item.qid}",
                        use_context=False, record_session=False,
                    )

    def test_article_evaluation_excludes_unannotated_and_refusal_questions(self):
        questions = build_qa(build_corpus())
        supported = next(item for item in questions if not item.should_refuse)
        refusal = next(item for item in questions if item.should_refuse)
        engine = MagicMock(config=self.config)
        engine.ask.return_value = Response(query="", answer="", refused=True)
        with tempfile.TemporaryDirectory() as tmp, patch(
            "core.evaluation.build_qa",
            return_value=[replace(supported, source_aids=[]), refusal],
        ):
            report = evaluate(engine, Path(tmp) / "report.json")
        self.assertEqual(report["article_grounded_retrieval_total"], 0)
        self.assertEqual(report["article_grounded_retrieval_accuracy"], 0.0)
        self.assertEqual(report["grounded_retrieval_accuracy"], 0.0)
        self.assertEqual(report["out_of_scope_refusal_accuracy"], 1.0)
        self.assertTrue(all(row["article_correct"] is None for row in report["rows"]))

    def test_builtin_evaluation_preserves_supported_answers_and_legacy_metrics(self):
        engine = HocVuEngine(self.config, self.searcher)
        engine.session = MagicMock()
        questions = build_qa(build_corpus())
        for item in questions:
            if not item.should_refuse:
                self.assertTrue(item.source_aids, item.question)
        with tempfile.TemporaryDirectory() as tmp:
            report = evaluate(engine, Path(tmp) / "report.json")
        self.assertEqual(report["grounded_retrieval_accuracy"], 1.0)
        # The stronger metric must not inherit the legacy metric's false
        # positives. Check genuinely supported examples without requiring
        # unrelated retrieval bugs to pass or pinning their current failures.
        representative_questions = {
            "Điểm TOEIC tối thiểu để học tiếng Anh chuyên ngành là bao nhiêu?",
            "Nghỉ học bao nhiêu phần trăm thì bị cấm thi?",
            "Sinh viên được bảo lưu tối đa bao nhiêu học kỳ?",
        }
        supported_rows = [
            row for row in report["rows"]
            if row["question"] in representative_questions
        ]
        self.assertEqual(len(supported_rows), len(representative_questions))
        self.assertTrue(all(row["article_correct"] is True for row in supported_rows))
        article_rows = [row for row in report["rows"] if row["article_correct"] is not None]
        self.assertEqual(report["article_grounded_retrieval_accuracy"], round(
            sum(row["article_correct"] for row in article_rows) / len(article_rows), 4,
        ))
        for row in article_rows:
            expected_match = not row["refused"] and any(
                ref["rid"] in row["expected_rids"] and ref["aid"] in row["expected_aids"]
                for ref in row["cited_articles"]
            )
            self.assertEqual(row["article_correct"], expected_match, row["question"])
        self.assertEqual(report["out_of_scope_refusal_accuracy"], 1.0)
        self.assertEqual(report["article_grounded_retrieval_total"],
                         sum(not item.should_refuse for item in questions))
        engine.session.add_turn.assert_not_called()

    def test_filters_expired_regulations_for_current_query(self):
        hits = self.searcher.search("Quy định cũ có cho phép thi lại không", 10, "2026-10-04")
        self.assertTrue(all(hit.chunk.valid_until != "2026-08-31" for hit in hits))

    def test_lets_unknown_topic_reach_retrieval_then_refuses_without_evidence(self):
        # Scope is determined by evidence, not a closed keyword allowlist.
        self.assertEqual(Classifier().classify("Căng tin trường có món gì?"), Intent.ACADEMIC_RULES)
        engine = HocVuEngine(self.config, self.searcher)
        for question in ("Căng tin trường có món gì?", "Xe bus tuyến nào đi ngang qua cổng chính của Đại học Hải Phòng?", "Trường có tổ chức giải bóng đá sinh viên không?"):
            with self.subTest(question=question):
                response = engine.ask(question, "out-of-scope", use_context=False, record_session=False)
                self.assertTrue(response.refused)

    def test_does_not_treat_thi_lai_as_a_greeting(self):
        classifier = Classifier()
        self.assertEqual(classifier.classify("thi lại"), Intent.ACADEMIC_RULES)
        self.assertEqual(classifier.classify("Khi nào thi học kỳ?"), Intent.ACADEMIC_RULES)

    def test_admits_administrative_document_question_but_blocks_casual_question(self):
        classifier = Classifier()
        self.assertEqual(classifier.classify("Tại sao một con vịt lại sinh ra một con gà?"), Intent.ACADEMIC_RULES)
        self.assertEqual(classifier.classify("Thời hạn cung cấp thông tin là khi nào?"), Intent.ACADEMIC_RULES)

    def test_stopwords_keep_academic_words_that_collide_after_accent_stripping(self):
        terms = content_tokens("Điểm rèn luyện tối đa là bao nhiêu? Quy định cũ có cho phép thi lại không?")
        self.assertIn("toi", terms)
        self.assertIn("da", terms)
        self.assertIn("thi", terms)
        self.assertIn("lai", terms)
        self.assertNotIn("la", terms)
        self.assertNotIn("bao", terms)
        self.assertNotIn("nhieu", terms)

    def test_academic_shorthand_and_synonyms_retrieve_the_right_clause(self):
        engine = HocVuEngine(self.config, self.searcher)
        cases = {
            "Điểm RL tối đa là bao nhiêu?": ("QD-RLSV-HPU-2026", "100 điểm"),
            "Nghỉ học bao nhiêu % thì bị cấm thi?": ("QD-DTDC-HPU-2026", "25%"),
            "Điều kiện để học song ngành là gì?": ("QD-DTDC-HPU-2026", "2.8"),
            "Điểm danh hộ bị xử lý ra sao?": ("QD-DTDC-HPU-2026", "trừ toàn bộ"),
        }
        for question, (rid, expected) in cases.items():
            with self.subTest(question=question):
                response = engine.ask(question, "synonyms", use_context=False, record_session=False)
                self.assertFalse(response.refused)
                self.assertEqual(response.references[0].rid, rid)
                self.assertIn(expected, response.answer)

    def test_proxy_attendance_paraphrases_cite_the_attendance_clause(self):
        engine = HocVuEngine(self.config, self.searcher)
        for question in (
            "Nếu điểm danh hộ thì bị xử lý như thế nào?",
            "Hình thức xử lý khi điểm danh hộ là gì?",
            "Sinh viên điểm danh hộ sẽ bị gì?",
            "Điểm danh hộ cho bạn thì bị phạt thế nào?",
            "diem danh ho bi xu ly ra sao",
        ):
            with self.subTest(question=question):
                response = engine.ask(question, "proxy-attendance", use_context=False, record_session=False)
                self.assertFalse(response.refused)
                self.assertEqual(response.references[0].rid, "QD-DTDC-HPU-2026")
                self.assertIn("trừ toàn bộ", response.answer)

    def test_sports_paraphrases_abstain_without_supporting_regulation(self):
        engine = HocVuEngine(self.config, self.searcher)
        for question in (
            "Trường có tổ chức giải bóng đá cho sinh viên không?",
            "Giải bóng đá sinh viên của trường tổ chức khi nào?",
            "Trường có đội bóng đá sinh viên không?",
            "Trường có tổ chức giải bóng chuyền sinh viên không?",
        ):
            with self.subTest(question=question):
                response = engine.ask(question, "sports", use_context=False, record_session=False)
                self.assertTrue(response.refused)
                self.assertFalse(response.references)

    def test_dormitory_subject_does_not_ground_an_unsupported_feature(self):
        engine = HocVuEngine(self.config, self.searcher)
        for question in (
            "Ký túc xá có wifi không?",
            "ky tuc xa co wifi khong",
            "Ký túc xá có WiFi không ạ?",
            "Ký túc xá có máy giặt không?",
            "ky tuc xa co may giat khong",
            "Wifi ở ký túc xá thế nào?",
            "wifi o ky tuc xa the nao",
            "Wifi tại ký túc xá như thế nào ạ?",
            "wifi tai ky tuc xa nhu the nao a",
            "Wifi trong ký túc xá ra sao?",
            "wifi trong ky tuc xa ra sao",
            "Wifi của ký túc xá thế nào?",
            "wifi cua ky tuc xa the nao",
            "Wifi ký túc xá thế nào?",
            "wifi ky tuc xa the nao",
            "Máy giặt ở ký túc xá thế nào?",
            "may giat o ky tuc xa the nao",
        ):
            with self.subTest(question=question):
                hits = self.searcher.search(question, 15)
                self.assertFalse(self.searcher.has_specific_evidence(question, hits))
                response = engine.ask(question, "dormitory-feature", use_context=False, record_session=False)
                self.assertTrue(response.refused)
                self.assertFalse(response.references)

        # The old ratio admits the subject's three syllables out of four;
        # ranking/coverage alone must not be treated as specific evidence.
        question = "Ký túc xá có wifi không?"
        dorm = next(hit for hit in self.searcher.search(question, 15) if "ký túc xá" in hit.chunk.text.lower())
        self.assertEqual(self.searcher.lexical_coverage(question, dorm), 0.75)

    def test_question_focus_can_be_grounded_in_new_documents(self):
        template = self.searcher.search("điểm rèn luyện", 1)[0]
        dorm_only = replace(template, chunk=replace(
            template.chunk, art_heading="Nội trú", text="Sinh viên chấp hành nội quy ký túc xá.",
        ))
        wifi_only = replace(template, chunk=replace(
            template.chunk, art_heading="Thư viện", text="Thư viện có wifi miễn phí.",
        ))
        grounded = replace(template, chunk=replace(
            template.chunk, art_heading="Dịch vụ nội trú", text="Ký túc xá có wifi miễn phí.",
        ))
        for question in (
            "Ký túc xá có wifi không?", "ky tuc xa co wifi khong",
            "Wifi ở ký túc xá thế nào?", "wifi o ky tuc xa the nao",
            "Wifi tại ký túc xá như thế nào ạ?", "wifi tai ky tuc xa nhu the nao a",
            "Wifi trong ký túc xá ra sao?", "wifi trong ky tuc xa ra sao",
            "Wifi của ký túc xá thế nào?", "wifi cua ky tuc xa the nao",
            "Wifi ký túc xá thế nào?", "wifi ky tuc xa the nao",
        ):
            with self.subTest(question=question):
                # Do not combine an unrelated feature clause with a subject
                # clause to manufacture support.
                self.assertFalse(self.searcher.has_specific_evidence(question, [dorm_only, wifi_only]))
                self.assertTrue(self.searcher.has_specific_evidence(question, [grounded]))
                engine = HocVuEngine(self.config, HybridSearcher(self.config))
                engine.searcher.build([grounded.chunk])
                response = engine.ask(question, "grounded-wifi", use_context=False, record_session=False)
                self.assertFalse(response.refused)
                self.assertTrue(response.references)
                self.assertIn("wifi", response.answer.lower())

    def test_descriptive_focus_preserves_diacritics_and_abbreviation_rules(self):
        self.assertEqual(self.searcher._question_focus("Wifi ở ký túc xá thế nào?"), "wifi")
        self.assertEqual(self.searcher._question_focus("wifi o ky tuc xa the nao"), "wifi")
        self.assertEqual(self.searcher._question_focus("Wifi ở ký túc xá thẻ nào?"), "")
        template = self.searcher.search("điểm rèn luyện", 1)[0]
        for question, text, expected in (
            ("Bóng ở ký túc xá thế nào?", "Ký túc xá có học bổng.", False),
            ("Điểm danh ở ký túc xá thế nào?", "Ký túc xá xét ĐRL.", False),
            ("diem danh o ky tuc xa the nao", "Ký túc xá xét ĐRL.", False),
            ("Điểm rèn luyện ở ký túc xá thế nào?", "Ký túc xá xét ĐRL.", True),
            ("diem ren luyen o ky tuc xa the nao", "Ký túc xá xét ĐRL.", True),
        ):
            with self.subTest(question=question):
                hit = replace(template, chunk=replace(template.chunk, art_heading="Nội trú", text=text))
                self.assertEqual(self.searcher.has_specific_evidence(question, [hit]), expected)

    def test_yes_no_focus_preserves_permissions_and_diacritics(self):
        self.assertEqual(self.searcher._yes_no_focus("Cơ sở có wifi không?"), "wifi")
        self.assertEqual(self.searcher._yes_no_focus("Cơ sở không đủ điều kiện"), "")
        engine = HocVuEngine(self.config, self.searcher)
        cases = {
            "Sinh viên có được bảo lưu không?": "QD-DTDC-HPU-2026",
            "sinh vien co duoc bao luu khong": "QD-DTDC-HPU-2026",
            "Bảo lưu có được không?": "QD-DTDC-HPU-2026",
            "bao luu co duoc khong": "QD-DTDC-HPU-2026",
            "Học lại 15% tín chỉ có ảnh hưởng đến bằng tốt nghiệp không?": "QD-TTTN-HPU-2026",
        }
        for question, rid in cases.items():
            with self.subTest(question=question):
                response = engine.ask(question, "yes-no-permission", use_context=False, record_session=False)
                self.assertFalse(response.refused)
                self.assertTrue(response.references)
                self.assertEqual(response.references[0].rid, rid)

    def test_unaccented_off_topic_questions_abstain(self):
        # Without diacritics "bong" also reads as "bổng" and "da" as "đa";
        # a lone syllable must not ground an answer in the scholarship text.
        engine = HocVuEngine(self.config, self.searcher)
        for question in (
            "truong co to chuc giai bong da sinh vien khong",
            "Truong co to chuc giai bong da cho sinh vien khong?",
            "giai bong da sinh vien cua truong to chuc khi nao",
            "truong co doi bong da sinh vien khong",
            "truong co to chuc giai bong chuyen sinh vien khong",
            "truong co san bong da khong",
            "bong ban",
            "can tin truong co mon gi",
            "gia com o can tin la bao nhieu",
            "xe bus tuyen nao di ngang qua cong chinh cua dai hoc hai phong",
        ):
            with self.subTest(question=question):
                response = engine.ask(question, "unaccented-off-topic", use_context=False, record_session=False)
                self.assertTrue(response.refused)
                self.assertFalse(response.references)

    def test_unaccented_academic_paraphrases_are_answered_with_citations(self):
        engine = HocVuEngine(self.config, self.searcher)
        cases = {
            "dieu kien bao luu ket qua hoc tap": ("QD-DTDC-HPU-2026", "Điều kiện bảo lưu"),
            "diem ren luyen toi da la bao nhieu": ("QD-RLSV-HPU-2026", "100 điểm"),
            "diem rl toi da la bao nhieu": ("QD-RLSV-HPU-2026", "100 điểm"),
            "bao luu": ("QD-DTDC-HPU-2026", "bảo lưu"),
            "hoc bong khuyen khich hoc tap": ("QD-HBHT-HPU-2026", "HBKKHT"),
            "nghi hoc bao nhieu phan tram thi bi cam thi": ("QD-DTDC-HPU-2026", "25%"),
            "tan sinh vien chua hoc xong ky 1 co duoc bao luu khong": ("QD-DTDC-HPU-2026", "bảo lưu"),
            "diem duoi bao nhieu thi phai hoc lai": ("QD-DTDC-HPU-2026", "học lại"),
            "thuc tap toi thieu bao nhieu tuan": ("QD-TTTN-HPU-2026", "12 tuần"),
        }
        for question, (rid, expected) in cases.items():
            with self.subTest(question=question):
                response = engine.ask(question, "unaccented-academic", use_context=False, record_session=False)
                self.assertFalse(response.refused)
                self.assertEqual(response.references[0].rid, rid)
                self.assertIn(expected, response.answer)

    def test_scholarship_conditions_cite_criteria_not_language_or_payment_rules(self):
        engine = HocVuEngine(self.config, self.searcher)
        for question in ("dieu kien nhan hoc bong", "Điều kiện nhận học bổng"):
            with self.subTest(question=question):
                hits = self.searcher.rerank_by_coverage(
                    question, self.searcher.search(question, 12, "2026-10-05"),
                )
                self.assertEqual(hits[0].chunk.rid, "QD-HBHT-HPU-2026")
                self.assertEqual(hits[0].chunk.aid, "Điều 1")
                self.assertIn("kết quả học tập và điểm rèn luyện", hits[0].chunk.text)
                response = engine.ask(
                    question, "scholarship-conditions", use_context=False,
                    record_session=False, ref_date="2026-10-05",
                )
                self.assertFalse(response.refused)
                self.assertEqual(response.references[0].rid, "QD-HBHT-HPU-2026")
                self.assertEqual(response.references[0].aid, "Điều 1")
                self.assertIn("kết quả học tập và điểm rèn luyện", response.answer)
                self.assertNotIn("TOEIC", response.answer)
                self.assertNotIn("chuyển khoản", response.answer)

    def test_scholarship_threshold_clauses_reach_coverage_reranking(self):
        engine = HocVuEngine(self.config, self.searcher)
        rid = "QD-HBHT-HPU-2026"
        for question in ("dieu kien nhan hoc bong", "Điều kiện nhận học bổng"):
            with self.subTest(question=question):
                # Reproduce the recall gap: the old pool loses every detailed
                # threshold, even though the general eligibility basis survives.
                old_pool = self.searcher.search(question, 12, "2026-10-05")
                self.assertFalse(any(
                    hit.chunk.rid == rid and hit.chunk.aid == "Điều 2"
                    for hit in old_pool
                ))
                with patch.object(
                    self.searcher, "rerank_by_coverage",
                    wraps=self.searcher.rerank_by_coverage,
                ) as rerank:
                    response = engine.ask(
                        question, "scholarship-thresholds", use_context=False,
                        record_session=False, ref_date="2026-10-05",
                    )
                rerank.assert_called_once()
                candidates = rerank.call_args.args[1]
                self.assertEqual(len(candidates), 20)
                expected = {"1": "3.6", "2": "3.2", "3": "2.5", "4": "15 tín chỉ"}
                for pool in (candidates, response.retrieved):
                    thresholds = {
                        cid: hit.chunk.text
                        for hit in pool
                        if hit.chunk.rid == rid and hit.chunk.aid == "Điều 2"
                        for cid in hit.chunk.clause_ids
                    }
                    self.assertEqual(set(thresholds), set(expected))
                    for cid, value in expected.items():
                        self.assertIn(value, thresholds[cid])
                self.assertFalse(response.refused)
                self.assertEqual(response.references[0].rid, rid)
                self.assertEqual(response.references[0].aid, "Điều 1")

    def test_candidate_pool_is_bounded_and_honours_larger_top_k(self):
        for top_k in (5, 24):
            with self.subTest(top_k=top_k):
                engine = HocVuEngine(replace(self.config, top_k=top_k), self.searcher)
                with patch.object(
                    self.searcher, "search", wraps=self.searcher.search,
                ) as search:
                    response = engine.ask(
                        "Điều kiện nhận học bổng", "bounded-pool",
                        use_context=False, record_session=False,
                        ref_date="2026-10-05",
                    )
                search.assert_called_once()
                self.assertEqual(search.call_args.args[1], max(top_k, 20))
                self.assertLessEqual(len(response.retrieved), max(top_k, 20))

    def test_larger_candidate_pool_keeps_unsupported_questions_refused(self):
        engine = HocVuEngine(self.config, self.searcher)
        for question in (
            "Điều kiện nhận học bổng bóng đá là gì?",
            "Wifi ở ký túc xá thế nào?",
            "Trường có tổ chức giải bóng đá sinh viên không?",
        ):
            with self.subTest(question=question):
                response = engine.ask(
                    question, "larger-pool-refusal", use_context=False,
                    record_session=False, ref_date="2026-10-05",
                )
                self.assertTrue(response.retrieved)
                self.assertTrue(response.refused)
                self.assertFalse(response.references)
                self.assertEqual(response.refusal_reason, "Insufficient grounded context")

    def test_evidence_matching_respects_vietnamese_diacritics(self):
        self.assertEqual(accent_key("hoà"), accent_key("hòa"))
        self.assertNotEqual(accent_key("bóng"), accent_key("bổng"))
        self.assertNotEqual(accent_key("đá"), accent_key("đa"))
        scholarship = next(hit for hit in self.searcher.search("học bổng doanh nghiệp", 5) if "bổng" in hit.chunk.text)
        self.assertEqual(HybridSearcher.lexical_coverage("bóng", scholarship), 0.0)
        # A student typing without diacritics still matches the accented text.
        self.assertEqual(HybridSearcher.lexical_coverage("hoc bong", scholarship), 1.0)
        self.assertEqual(HybridSearcher.lexical_coverage("học bổng", scholarship), 1.0)

    def test_abbreviation_supports_its_whole_phrase_not_a_lone_syllable(self):
        weak_training = next(hit for hit in self.searcher.search("ĐRL xếp loại Yếu", 5) if "ĐRL xếp loại Yếu" in hit.chunk.text)
        self.assertEqual(HybridSearcher.lexical_coverage("điểm rèn luyện", weak_training), 1.0)
        self.assertEqual(HybridSearcher.lexical_coverage("điểm danh", weak_training), 0.0)

    def test_coverage_uses_the_best_retrieved_clause_not_only_rank_one(self):
        engine = HocVuEngine(self.config, self.searcher)
        response = engine.ask("Điểm thực tập được tính như thế nào?", "coverage", use_context=False, record_session=False)
        self.assertFalse(response.refused)
        self.assertIn("40%", response.answer)
        self.assertEqual(response.references[0].rid, "QD-TTTN-HPU-2026")

    def test_numeric_inference_is_shown_with_its_source_formula(self):
        engine = HocVuEngine(self.config, self.searcher)
        response = engine.ask("Hiến máu 2 lần được cộng mấy điểm?", "numeric", use_context=False, record_session=False)
        self.assertFalse(response.refused)
        self.assertIn("2 lần × 10 điểm/lần = 20 điểm", response.answer)
        self.assertEqual(response.references[0].rid, "QD-RLSV-HPU-2026")

    def test_old_rule_can_be_retrieved_when_explicitly_requested(self):
        engine = HocVuEngine(self.config, self.searcher)
        response = engine.ask("Quy định cũ có cho phép thi lại không?", "historical", use_context=False, record_session=False)
        self.assertFalse(response.refused)
        self.assertEqual(response.references[0].rid, "QD-DTDC-HPU-2024")
        self.assertIn("thi lại 1 lần", response.answer)

    def test_comparison_uses_both_regulation_versions(self):
        engine = HocVuEngine(self.config, self.searcher)
        response = engine.ask("Quy định 2026 khác gì 2024 về thi lại?", "comparison", use_context=False, record_session=False)
        self.assertFalse(response.refused)
        self.assertEqual({reference.rid for reference in response.references}, {"QD-DTDC-HPU-2024", "QD-DTDC-HPU-2026"})
        self.assertIn("2024:", response.answer)
        self.assertIn("2026:", response.answer)
        self.assertIn("Không tổ chức thi lại", response.answer)

    def test_explains_absence_and_training_as_a_grounded_condition(self):
        question = "Tôi nghỉ 5 tiết học thì điểm rèn luyện bị ảnh hưởng như nào?"
        self.assertTrue(is_attendance_training_scenario(question))
        hits = self.searcher.search(expand_retrieval_query(question), 8, "2026-10-05")
        result = Generator(self.config).generate_attendance_training_scenario(hits, question)
        self.assertIsNotNone(result)
        answer, references = result
        self.assertIn("không quy định mức trừ", answer)
        self.assertIn("25%", answer)
        self.assertIn("5 tiết", answer)
        self.assertNotIn("3 tiết", answer)
        self.assertGreaterEqual(len(references), 2)

    def test_attendance_scenario_does_not_match_nghiep(self):
        self.assertFalse(is_attendance_training_scenario("Nghiệp vụ điểm rèn luyện có 3 tiết thực hành"))

    def test_bm25_refuses_a_query_with_only_generic_overlap(self):
        engine = HocVuEngine(self.config, self.searcher)
        engine.session = MagicMock()
        engine.session.contextualize.return_value = ("cho tôi biết thông tin chi tiết về tín chỉ xyzquux blabla nonsense", "")
        response = engine.ask("cho tôi biết thông tin chi tiết về tín chỉ xyzquux blabla nonsense", "test-refusal")
        self.assertTrue(response.refused)
        self.assertLess(response.confidence, self.config.lexical_coverage_floor)

    def test_rebuild_reuses_the_searcher_built_for_the_new_index(self):
        engine = HocVuEngine(self.config, self.searcher)
        replacement = HybridSearcher(self.config)
        with patch("core.engine.build_index", return_value=({"chunks": 1}, replacement)) as build:
            result = engine.rebuild_index()
        self.assertEqual(result["chunks"], 1)
        self.assertIs(engine.searcher, replacement)
        build.assert_called_once_with(self.config, return_searcher=True)

    def test_follow_up_uses_recent_academic_context(self):
        engine = HocVuEngine(self.config, self.searcher)
        engine.session = MagicMock()
        engine.session.get_history.return_value = [{"question": "Điều kiện bảo lưu là gì?"}]
        engine.session.contextualize.return_value = ("Điều kiện bảo lưu là gì? | Còn điều kiện nào khác?", "Điều kiện bảo lưu là gì?")
        response = engine.ask("Còn điều kiện nào khác?", "test-follow-up")
        self.assertFalse(response.refused)
        self.assertEqual(response.intent, Intent.ACADEMIC_RULES.value)

    def test_index_schema_version_is_saved_and_unknown_versions_fail_clearly(self):
        with tempfile.TemporaryDirectory() as directory:
            index_path = Path(directory) / "index.json"
            self.searcher.save(index_path)
            self.assertEqual(json.loads(index_path.read_text(encoding="utf-8"))["schema_version"], 2)
            index_path.write_text(json.dumps({"schema_version": 999, "chunks": []}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "schema version"):
                HybridSearcher.load(str(index_path), self.config)

    def test_startup_rebuilds_index_built_by_another_article_version(self):
        from core.documents import DocumentRepository
        current = DocumentRepository.article_build_version()
        replacement = HybridSearcher(self.config)
        with tempfile.TemporaryDirectory() as directory:
            index_path = Path(directory) / "index.json"
            for saved_version in (None, "extraction-0.articles-0"):
                self.searcher.save(index_path, article_version=saved_version, index_fingerprint=index_fingerprint(self.config))
                with patch("core.engine.build_index", return_value=({"chunks": 0}, replacement)) as build:
                    engine = HocVuEngine.load_or_build(self.config, index_path)
                build.assert_called_once()
                self.assertIs(engine.searcher, replacement)

    def test_startup_loads_current_index_without_rebuilding(self):
        from core.documents import DocumentRepository
        with tempfile.TemporaryDirectory() as directory:
            index_path = Path(directory) / "index.json"
            self.searcher.save(index_path, article_version=DocumentRepository.article_build_version(), index_fingerprint=index_fingerprint(self.config))
            with patch("core.engine.build_index") as build:
                engine = HocVuEngine.load_or_build(self.config, index_path)
            build.assert_not_called()
            self.assertEqual(len(engine.searcher.chunks), len(self.searcher.chunks))

    def test_corrupt_index_uses_last_atomic_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            index_path = Path(directory) / "index.json"
            self.searcher.save(index_path)
            self.searcher.save(index_path)
            index_path.write_text("{broken", encoding="utf-8")
            restored = HybridSearcher.load(str(index_path), self.config)
            self.assertEqual(len(restored.chunks), len(self.searcher.chunks))

    def test_api_response_hides_raw_retrieval_by_default(self):
        response = Response(query="q", answer="a", retrieved=self.searcher.search("bảo lưu", 1))
        self.assertNotIn("retrieved", response.to_dict())
        self.assertIn("retrieved", response.to_dict(include_retrieved=True))

    def test_empty_question_is_not_persisted(self):
        engine = HocVuEngine(self.config, self.searcher)
        engine.session = MagicMock()
        engine.ask("", "empty-session")
        engine.session.add_turn.assert_not_called()

    def test_semantic_query_error_falls_back_to_bm25(self):
        self.searcher.semantic = MagicMock()
        self.searcher.semantic.available = True
        self.searcher.semantic.similarities.side_effect = RuntimeError("model unavailable")
        hits = self.searcher.search("điều kiện bảo lưu", 1)
        self.assertTrue(hits)
        self.assertIsNone(self.searcher.semantic)
        self.assertIn("Semantic query fallback", self.searcher.semantic_error)

    def test_grounded_response_includes_structured_answer_card(self):
        engine = HocVuEngine(self.config, self.searcher)
        engine.session = MagicMock()
        engine.session.contextualize.return_value = ("Điều kiện bảo lưu kết quả học tập là gì?", "")
        response = engine.ask("Điều kiện bảo lưu kết quả học tập là gì?", "card-session")
        card = response.to_dict()["card"]
        self.assertTrue(response.references)
        self.assertTrue(card["verdict_segments"])
        self.assertEqual(card["verdict_segments"][0]["cites"], [1])
        self.assertGreaterEqual(card["grounding"]["level"], 2)
        self.assertEqual(card["grounding"]["source_count"], len(response.references))
        self.assertIn("answer", response.to_dict())
        self.assertIn("references", response.to_dict())

    def test_refusal_card_contains_answerable_suggestions(self):
        engine = HocVuEngine(self.config, self.searcher)
        engine.session = MagicMock()
        response = engine.ask("Con vịt có biết lập trình không?", "refusal-card", use_context=False)
        self.assertTrue(response.refused)
        self.assertEqual(len(response.card["suggestions"]), 3)
        self.assertNotIn("Con vịt có biết lập trình không?", response.card["suggestions"])
        suggested = {question for topic in engine.suggestion_topics() for question in topic["questions"]}
        self.assertTrue(set(response.card["suggestions"]).issubset(suggested))


class UploadedFeatureEvidenceTests(unittest.TestCase):
    @staticmethod
    def service_docx(clause):
        """Create a Word package, not pre-extracted text or search chunks."""
        content = io.BytesIO()
        with zipfile.ZipFile(content, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", (
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                '<Default Extension="xml" ContentType="application/xml"/>'
                '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                '</Types>'
            ))
            archive.writestr("_rels/.rels", (
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
                '</Relationships>'
            ))
            archive.writestr("word/document.xml", (
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                '<w:body><w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>'
                '<w:r><w:t>Dịch vụ nội trú</w:t></w:r></w:p>'
                f'<w:p><w:r><w:t>{escape(clause)}</w:t></w:r></w:p>'
                '</w:body></w:document>'
            ))
        return content.getvalue()

    def test_descriptive_wifi_answers_require_support_in_uploaded_docx(self):
        questions = (
            "Wifi ở ký túc xá thế nào?", "wifi o ky tuc xa the nao",
            "Wifi tại ký túc xá như thế nào ạ?", "wifi tai ky tuc xa nhu the nao a",
            "Wifi trong ký túc xá ra sao?", "wifi trong ky tuc xa ra sao",
            "Wifi của ký túc xá thế nào?", "wifi cua ky tuc xa the nao",
            "Wifi ký túc xá thế nào?", "wifi ky tuc xa the nao",
        )
        for supported, clause in (
            (False, "Sinh viên chấp hành nội quy ký túc xá."),
            (True, "Ký túc xá có wifi miễn phí cho sinh viên ở ký túc xá."),
        ):
            with self.subTest(supported=supported), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                index = root / "index" / "chunks.json"
                config = AppConfig(semantic_enabled=False, llm_backend="local", seed=20262027)
                with (
                    patch("core.engine.DOCS", root / "documents"),
                    patch("core.engine.SESSION_DB", root / "sessions.db"),
                    patch("core.engine.AUD", root / "audio"),
                    # Redirect the default index path bound by build_index,
                    # while still running the real rebuild implementation.
                    patch("core.engine.build_index", side_effect=lambda cfg, **kw: build_index(
                        cfg, index_path=index, **kw,
                    )),
                ):
                    engine = HocVuEngine(config, HybridSearcher(config))
                    uploaded = engine.documents.add(
                        "dich-vu-noi-tru.docx", self.service_docx(clause),
                        metadata={"document_date": "2026-01-01"},
                    )
                    extracted = root / "documents" / "extracted" / f"{uploaded['id']}.txt"
                    self.assertIn(clause, extracted.read_text(encoding="utf-8"))
                    self.assertEqual(engine.rebuild_index()["uploaded"], 1)
                    self.assertTrue(index.is_file())
                    engine = HocVuEngine.load(config, index)
                    self.assertEqual(engine.searcher.provider, "bm25")
                    self.assertTrue(any(
                        chunk.rid == uploaded["rid"] and clause in chunk.text
                        for chunk in engine.searcher.chunks
                    ))
                    for question in questions:
                        with self.subTest(question=question):
                            response = engine.ask(
                                question, "uploaded-wifi", ref_date="2026-10-18",
                                use_context=False, record_session=False,
                            )
                            self.assertEqual(response.refused, not supported)
                            if not supported:
                                self.assertFalse(response.references)
                                continue
                            self.assertIn("wifi miễn phí", response.answer.lower())
                            self.assertTrue(response.references)
                            for reference in response.references:
                                self.assertEqual(reference.rid, uploaded["rid"])
                                self.assertEqual(reference.reg_title, uploaded["title"])
                                self.assertEqual(reference.aid, "Mục 1")
                                self.assertEqual(reference.art_heading, "Dịch vụ nội trú")
                                self.assertEqual(reference.clause_ids, ["1"])
                                self.assertIn(clause, reference.excerpt)


class SemanticFeatureEvidenceTests(unittest.TestCase):
    questions = (
        "Wifi ở ký túc xá thế nào?", "wifi o ky tuc xa the nao",
        "Wifi tại ký túc xá như thế nào ạ?", "wifi tai ky tuc xa nhu the nao a",
        "Wifi trong ký túc xá ra sao?", "wifi trong ky tuc xa ra sao",
        "Wifi của ký túc xá thế nào?", "wifi cua ky tuc xa the nao",
        "Wifi ký túc xá thế nào?", "wifi ky tuc xa the nao",
    )
    ref_date = "2026-10-05"

    @classmethod
    def setUpClass(cls):
        cls.chunks = [
            chunk for regulation in build_corpus()
            for chunk in split_regulation(regulation, 800, 1)
        ]

    def make_searcher(self, chunks):
        config = AppConfig(max_units=2, semantic_enabled=True)
        # Stub only the encoder, not retrieval or evidence checks. Even
        # unsupported clauses receive near-perfect semantic similarity.
        with patch("core.searcher.SemanticEncoder") as encoder_type:
            encoder = encoder_type.return_value
            encoder.available = True
            encoder.cache_error = ""
            encoder.build.return_value = True
            encoder.similarities.return_value = [0.99] * len(chunks)
            searcher = HybridSearcher(config)
            searcher.build(chunks)
            encoder_type.assert_called_once()
            encoder.build.assert_called_once_with(
                [f"{chunk.art_heading}\n{chunk.text}" for chunk in chunks],
                index_fingerprint=index_fingerprint(config),
            )
        self.assertEqual(searcher.provider, "bm25+multilingual-e5")
        self.assertEqual(searcher.semantic_error, "")
        return searcher, encoder

    def ask(self, searcher, encoder, question):
        encoder.similarities.reset_mock()
        with patch("core.engine.SessionStore", return_value=MagicMock()):
            engine = HocVuEngine(searcher.config, searcher)
        response = engine.ask(
            question, "semantic-feature", use_context=False,
            record_session=False, ref_date=self.ref_date,
        )
        encoder.similarities.assert_called_once_with(expand_retrieval_query(question))
        engine.session.add_turn.assert_not_called()
        self.assertEqual(response.providers["retrieval"], "bm25+multilingual-e5")
        self.assertTrue(response.retrieved)
        self.assertTrue(all(hit.vec == 0.99 for hit in response.retrieved))
        return response

    def test_high_semantic_scores_do_not_ground_unsupported_builtin_features(self):
        searcher, encoder = self.make_searcher(self.chunks)
        for question in self.questions + (
            "Máy giặt ở ký túc xá thế nào?", "may giat o ky tuc xa the nao",
        ):
            with self.subTest(question=question):
                hits = searcher.search(question, len(self.chunks), self.ref_date)
                self.assertTrue(hits)
                self.assertTrue(all(hit.vec == 0.99 for hit in hits))
                peak = max(hit.bm25 for hit in hits)
                self.assertGreater(peak, 0)
                for hit in hits:
                    self.assertAlmostEqual(
                        hit.score,
                        searcher.config.bm25_weight * hit.bm25 / peak
                        + (1 - searcher.config.bm25_weight) * hit.vec,
                    )
                dorm = next(hit for hit in hits if "ký túc xá" in hit.chunk.text.lower())
                self.assertGreaterEqual(searcher.lexical_coverage(question, dorm), 0.5)
                self.assertFalse(searcher.has_specific_evidence(question, hits))
                response = self.ask(searcher, encoder, question)
                self.assertTrue(response.refused)
                self.assertFalse(response.references)
                self.assertEqual(response.refusal_reason, "Insufficient grounded context")

    def test_semantic_feature_answers_require_support_in_the_same_clause(self):
        template = self.chunks[0]
        dorm_only = replace(
            template, cid="feature-dorm", art_heading="Nội trú",
            text="Sinh viên chấp hành nội quy ký túc xá.",
        )
        wifi_only = replace(
            template, cid="feature-library", art_heading="Thư viện",
            text="Thư viện có wifi miễn phí.",
        )
        grounded = replace(
            template, cid="feature-supported", art_heading="Dịch vụ nội trú",
            text="Ký túc xá có wifi miễn phí.",
        )
        for supported, chunks in (
            (False, [dorm_only, wifi_only]),
            (True, [dorm_only, wifi_only, grounded]),
        ):
            searcher, encoder = self.make_searcher(chunks)
            for question in self.questions:
                with self.subTest(question=question, supported=supported):
                    response = self.ask(searcher, encoder, question)
                    self.assertEqual(
                        searcher.has_specific_evidence(question, response.retrieved), supported,
                    )
                    self.assertEqual(response.refused, not supported)
                    if supported:
                        self.assertTrue(response.references)
                        self.assertIn(grounded.text, response.references[0].excerpt)
                        self.assertIn("wifi miễn phí", response.answer.lower())
                    else:
                        self.assertFalse(response.references)
                        self.assertEqual(response.refusal_reason, "Insufficient grounded context")


if __name__ == "__main__":
    unittest.main()
