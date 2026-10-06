"""Application orchestration for the grounded academic-regulation assistant."""
from __future__ import annotations

import time
from datetime import date
from pathlib import Path

from .classifier import Classifier, Intent
from .cards import best_suggestions, build_card, build_suggestion_topics
from .corpus import build_corpus
from .documents import DocumentRepository
from .generator import DECLINE_MSG, Generator
from .llm import GroundedLLM, LLMError
from .models import Response
from .searcher import HybridSearcher
from .scenarios import expand_retrieval_query, is_attendance_training_scenario, is_contextual_follow_up
from .session import SessionStore
from .settings import AUD, DOCS, INDEX_JSON, SESSION_DB, AppConfig
from .splitter import split_regulation
from .voice import VoiceManager


def build_index(config: AppConfig, *, return_searcher: bool = False):
    repository = DocumentRepository(DOCS)
    corpus = build_corpus(seed=config.seed) + repository.regulations()
    chunks = [chunk for regulation in corpus for chunk in split_regulation(regulation, config.max_chunk_chars, config.overlap_sents)]
    searcher = HybridSearcher(config)
    searcher.build(chunks)
    searcher.save(str(INDEX_JSON))
    result = {"chunks": len(chunks), "documents": len(corpus), "uploaded": len(repository.list())}
    # Reuse this instance after upload/reindex. Loading a just-saved index
    # would build semantic embeddings a second time on the same corpus.
    return (result, searcher) if return_searcher else result


class HocVuEngine:
    def __init__(self, config: AppConfig, searcher: HybridSearcher):
        self.config = config
        self.searcher = searcher
        self.classifier = Classifier()
        self.generator = Generator(config)
        self.llm = GroundedLLM(config)
        self.voice = VoiceManager(config, AUD)
        self.session = SessionStore(SESSION_DB)
        self.documents = DocumentRepository(DOCS)
        self._suggestion_topics = build_suggestion_topics(config.seed)

    @classmethod
    def load(cls, config: AppConfig, index_path: Path):
        return cls(config, HybridSearcher.load(str(index_path), config))

    def ask(self, question: str, session_id: str, ref_date: str | None = None, with_audio: bool = False, use_context: bool = True, use_ai: bool = False, record_session: bool = True) -> Response:
        started = time.perf_counter()
        question = (question or "").strip()
        intent = self.classifier.classify(question)
        follow_up = intent == Intent.OUT_OF_SCOPE and use_context and is_contextual_follow_up(question) and bool(self.session.get_history(session_id, 1))
        if follow_up:
            intent = Intent.ACADEMIC_RULES
        refused, reason, references, hits, confidence = False, "", [], [], 0.0
        ai_status = "off"
        if not question:
            answer, refused, reason = "Bạn hãy nhập câu hỏi về quy chế đào tạo.", True, "Empty question"
        elif intent == Intent.GREETING:
            answer, confidence = "Chào bạn! Tôi hỗ trợ tra cứu quy chế đào tạo. Bạn có thể hỏi về tín chỉ, đăng ký học phần, bảo lưu, tốt nghiệp hoặc học vụ.", 1.0
        elif intent == Intent.TOXIC:
            answer, refused, reason = "Tôi chỉ hỗ trợ các câu hỏi về quy chế đào tạo trong môi trường an toàn.", True, "Unsafe request"
        elif intent == Intent.OUT_OF_SCOPE:
            answer, refused, reason = "Tôi chỉ hỗ trợ tra cứu quy chế đào tạo, như tín chỉ, học phần, học vụ, bảo lưu, tốt nghiệp và kỷ luật học tập.", True, "Out of scope"
        else:
            scenario = is_attendance_training_scenario(question)
            retrieval_question = expand_retrieval_query(question)
            if use_context:
                retrieval_question, _ = self.session.contextualize(session_id, retrieval_question)
            # Situation questions may need evidence from two regulations (for
            # example attendance and training score), so retain a wider pool
            # before the scenario generator selects only relevant passages.
            hits = self.searcher.search(retrieval_question, max(self.config.top_k, 20) if scenario else self.config.top_k, ref_date or date.today().isoformat())
            using_semantic = self.searcher.provider != "bm25"
            lexical_coverage = self.searcher.lexical_coverage(retrieval_question, hits[0]) if hits else 0.0
            confidence = min(1.0, hits[0].score) if using_semantic and hits else lexical_coverage
            floor = self.config.semantic_floor if using_semantic else self.config.lexical_coverage_floor
            # Scenario expansion deliberately adds the regulation vocabulary
            # needed to retrieve both attendance and training-score evidence.
            if scenario and not using_semantic:
                floor = min(floor, 0.30)
            if follow_up and not using_semantic:
                # The pronouns in a short follow-up are intentionally not in
                # the document; its earlier turn supplies the actual topic.
                floor = min(floor, 0.40)
            if not hits or confidence < floor:
                answer, refused, reason = DECLINE_MSG, True, "Insufficient grounded context"
            else:
                scenario_answer = self.generator.generate_attendance_training_scenario(hits, question) if scenario else None
                answer, references = scenario_answer or self.generator.generate(question, hits)
                refused = not bool(references)
                reason = "Insufficient grounded context" if refused else ""
                if use_ai and not refused:
                    try:
                        answer = self.llm.rewrite(question, answer, references)
                        ai_status = "on"
                    except LLMError as exc:
                        ai_status = "fallback"
                        reason = str(exc)
        response = Response(
            query=question, answer=answer, references=references, confidence=confidence,
            refused=refused, refusal_reason=reason, intent=intent.value, retrieved=hits,
            audio_url=None, providers={"retrieval": self.searcher.provider, "voice": "browser", "llm": ai_status},
            timing={"total_ms": (time.perf_counter() - started) * 1000}, session_id=session_id,
            metadata={"grounded": bool(references), "ai_mode": ai_status, "lexical_coverage": round(lexical_coverage if 'lexical_coverage' in locals() else 0.0, 4)},
            card=build_card(answer, references, hits, confidence, best_suggestions(question, self._suggestion_topics) if refused else None),
        )
        if record_session and question:
            self.session.add_turn(session_id, question, answer, intent.value, references[0].aid if references else "", references[0].rid if references else "")
        return response

    def suggestion_topics(self) -> list[dict]:
        return self._suggestion_topics

    def ask_voice(self, audio_path: str, session_id: str, with_audio: bool = True, ref_date: str | None = None) -> Response:
        speech = self.voice.speech_to_text(audio_path)
        response = Response(
            query="", answer="Bản thử nghiệm dùng nhận dạng giọng nói của trình duyệt. Hãy thử lại bằng Chrome/Edge hoặc nhập câu hỏi bằng văn bản.",
            refused=True, refusal_reason="Server-side STT unavailable", intent=Intent.ACADEMIC_RULES.value,
            speech=speech, session_id=session_id, providers={"voice": "browser"},
        )
        response.speech = speech
        return response

    def list_documents(self) -> list[dict]:
        docs = {}
        chunk_counts = {}
        for chunk in self.searcher.chunks:
            chunk_counts[chunk.rid] = chunk_counts.get(chunk.rid, 0) + 1
            docs.setdefault(chunk.rid, {"rid": chunk.rid, "title": chunk.reg_title, "version": chunk.version, "valid_from": chunk.valid_from, "valid_until": chunk.valid_until, "kind": "demo"})
        for rid, doc in docs.items():
            doc["chunk_count"] = chunk_counts.get(rid, 0)
        for item in self.documents.list():
            docs[item["rid"]] = {
                **item, "kind": "uploaded",
                "version": f"Quyết định {item['decision_number']}" if item.get("decision_number") else "Tải lên",
                "valid_from": item.get("document_date") or item["uploaded_at"][:10],
                "valid_until": None, "chunk_count": chunk_counts.get(item["rid"], 0),
            }
        return list(docs.values())

    def add_document(self, filename: str, content: bytes, use_ocr: bool = False, metadata: dict | None = None) -> dict:
        item = self.documents.add(filename, content, use_ocr=use_ocr, metadata=metadata)
        _, self.searcher = build_index(self.config, return_searcher=True)
        return item

    def remove_document(self, item_id: str) -> None:
        self.documents.remove(item_id)
        _, self.searcher = build_index(self.config, return_searcher=True)

    def document_text(self, item_id: str) -> dict:
        result = self.documents.get_text(item_id)
        item = next((entry for entry in self.documents.list() if entry["id"] == item_id), None)
        result["chunk_count"] = sum(1 for chunk in self.searcher.chunks if item and chunk.rid == item["rid"])
        return result

    def rebuild_index(self) -> dict:
        result, self.searcher = build_index(self.config, return_searcher=True)
        return result

    def list_sources(self) -> list[dict]:
        return [chunk.to_dict() for chunk in self.searcher.chunks]

    def history(self, session_id: str) -> list[dict]:
        return self.session.get_history(session_id, self.config.max_history)
