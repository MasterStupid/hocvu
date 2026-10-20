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
from .index_version import index_fingerprint
from .llm import GroundedLLM, LLMError
from .models import Regulation, Response
from .searcher import HybridSearcher, StaleIndexError
from .scenarios import comparison_subjects, comparison_topic, expand_retrieval_query, is_attendance_training_scenario, is_comparison_query, is_context_dependent, is_contextual_follow_up, is_historical_query, is_version_comparison_query
from .session import SessionStore
from .settings import AUD, DOCS, INDEX_JSON, SESSION_DB, AppConfig
from .splitter import split_regulation
from .voice import VoiceManager


def build_index(
    config: AppConfig, *, return_searcher: bool = False, index_path: Path = INDEX_JSON,
    uploaded_regulations: list[Regulation] | None = None,
    document_entries: list[dict] | None = None,
):
    if uploaded_regulations is None:
        repository = DocumentRepository(DOCS)
        entries = repository.list()
        uploaded_regulations = repository.regulations(entries=entries)
    else:
        if document_entries is None:
            raise ValueError("An explicit uploaded corpus requires its manifest snapshot.")
        entries = DocumentRepository._ordered_entries(document_entries)
    corpus = build_corpus(seed=config.seed) + uploaded_regulations
    # Hash the exact snapshot used for chunks, including extraction upgrades.
    # Recovery supplies its confirmed, not-yet-published metadata snapshot.
    fingerprint = index_fingerprint(config, DOCS, document_entries=entries)
    chunks = [chunk for regulation in corpus for chunk in split_regulation(regulation, config.max_chunk_chars, config.overlap_sents)]
    searcher = HybridSearcher(config)
    searcher.build(chunks)
    searcher.save(str(index_path), article_version=DocumentRepository.article_build_version(), index_fingerprint=fingerprint)
    result = {"chunks": len(chunks), "documents": len(corpus), "uploaded": len(uploaded_regulations)}
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
        return cls.load_or_build(config, index_path)

    @classmethod
    def load_or_build(cls, config: AppConfig, index_path: Path):
        """Load the saved index, rebuilding it when missing or stale.

        Check uploaded-document extraction versions and a fingerprint of the
        built-in corpus, splitter, chunking settings and uploaded manifest. A matching index is
        loaded as is; older indexes without metadata are rebuilt once.
        """
        if index_path.exists():
            try:
                searcher = HybridSearcher.load(
                    str(index_path), config,
                    article_version=DocumentRepository.article_build_version(),
                    index_fingerprint=index_fingerprint(config, DOCS),
                )
                return cls(config, searcher)
            except StaleIndexError as exc:
                print(f"Rebuilding search index: {exc}")
        _, searcher = build_index(config, return_searcher=True, index_path=index_path)
        return cls(config, searcher)

    def ask(self, question: str, session_id: str, ref_date: str | None = None, with_audio: bool = False, use_context: bool = True, use_ai: bool = False, record_session: bool = True) -> Response:
        started = time.perf_counter()
        self.ensure_session_open(session_id)
        question = (question or "").strip()
        intent = self.classifier.classify(question)
        refused, reason, references, hits, confidence = False, "", [], [], 0.0
        ai_status = "off"
        context_question = context_root = question
        if not question:
            answer, refused, reason = "Bạn hãy nhập câu hỏi về quy chế đào tạo.", True, "Empty question"
        elif intent == Intent.GREETING:
            answer, confidence = "Chào bạn! Tôi hỗ trợ tra cứu quy chế đào tạo. Bạn có thể hỏi về tín chỉ, đăng ký học phần, bảo lưu, tốt nghiệp hoặc học vụ.", 1.0
        elif intent == Intent.TOXIC:
            answer, refused, reason = "Tôi chỉ hỗ trợ các câu hỏi về quy chế đào tạo trong môi trường an toàn.", True, "Unsafe request"
        else:
            scenario = is_attendance_training_scenario(question)
            comparison = is_comparison_query(question)
            version_comparison = is_version_comparison_query(question)
            subjects = comparison_subjects(question) if comparison and not version_comparison else ()
            historical = version_comparison or is_historical_query(question)
            retrieval_question = expand_retrieval_query(comparison_topic(question) if comparison else question)
            is_follow_up = is_contextual_follow_up(question)
            # Coverage can only rerank clauses present in this bounded pool.
            # Eligibility thresholds can rank below the first 12 BM25 hits
            # when generic "conditions/receive" wording favours other rules.
            # Keep recall separate from the unchanged evidence/refusal gates.
            retrieval_limit = max(self.config.top_k, 20)
            today_str = ref_date or date.today().isoformat()

            def retrieve(query):
                return self.searcher.rerank_by_coverage(
                    query, self.searcher.search(
                        query, retrieval_limit, today_str, include_expired=historical,
                    ),
                )

            # Always try the current subject first. A discourse prefix such as
            # "Thế còn học phí?" must not force a previous, unrelated topic in.
            hits = retrieve(retrieval_question)
            if subjects:
                # Give both sides their own bounded retrieval allowance;
                # combined-query ranking can otherwise omit the shorter side.
                by_id = {(hit.chunk.rid, hit.chunk.cid): hit for hit in hits}
                for subject in subjects:
                    for hit in retrieve(expand_retrieval_query(subject)):
                        by_id.setdefault((hit.chunk.rid, hit.chunk.cid), hit)
                hits = list(by_id.values())
            dependent = is_context_dependent(question)
            context_used = False
            # A connective alone does not license borrowing evidence for an
            # unsupported new subject ("Thế còn wifi?"). Only an actual
            # reference/ellipsis needs its antecedent to resolve the query.
            if use_context and is_follow_up and dependent:
                context_q, root = self.session.contextualize(
                    session_id, retrieval_question, limit=self.config.max_history,
                )
                if context_q != retrieval_question:
                    context_hits = retrieve(context_q)
                    if self.searcher.has_specific_evidence(context_q, context_hits):
                        hits, retrieval_question = context_hits, context_q
                        context_used = True
                        context_question, context_root = context_q, root
            # Generic "conditions" can match any regulation. Without a usable
            # antecedent, never answer a reference-only question from such hits.
            if dependent and not context_used:
                hits = []
            if historical and not comparison:
                # When the student explicitly asks for the old rule, an
                # expired source is the intended evidence, not a fallback.
                expired = [hit for hit in hits if hit.chunk.valid_until]
                hits = expired + [hit for hit in hits if not hit.chunk.valid_until]
            # Query-time fallback is local to this response; the encoder stays
            # available for a later retry. Do not use raw BM25 as cosine confidence.
            using_semantic = any(hit.vec != 0 for hit in hits)
            lexical_coverage = self.searcher.lexical_coverage(retrieval_question, hits)
            confidence = min(1.0, hits[0].score) if using_semantic and hits else lexical_coverage
            floor = self.config.semantic_floor if using_semantic else self.config.lexical_coverage_floor
            # Scenario expansion deliberately adds the regulation vocabulary
            # needed to retrieve both attendance and training-score evidence.
            if scenario and not using_semantic:
                floor = min(floor, 0.30)
            if is_follow_up and context_used and not using_semantic:
                # The pronouns in a short follow-up are intentionally not in
                # the document; its earlier turn supplies the actual topic.
                floor = min(floor, 0.40)
            specific_evidence = self.searcher.has_specific_evidence(retrieval_question, hits)
            if comparison and not version_comparison:
                selected = self.generator.select_comparison_evidence(question, hits)
                # A comparison is supported only when *each* requested side is
                # grounded. Pool-wide max coverage cannot establish that.
                specific_evidence = bool(selected)
                lexical_coverage = min((
                    self.searcher.lexical_coverage(subject, hit)
                    for subject, hit in zip(subjects, selected)
                ), default=0.0)
                confidence = min((
                    min(1.0, hit.score) if hit.vec != 0
                    else self.searcher.lexical_coverage(subject, hit)
                    for subject, hit in zip(subjects, selected)
                ), default=0.0)
                floor = 0.0  # Per-side lexical/semantic floors were checked above.
            if not hits or confidence < floor or not specific_evidence:
                answer, refused, reason = DECLINE_MSG, True, "Insufficient grounded context"
            else:
                scenario_answer = self.generator.generate_attendance_training_scenario(hits, question) if scenario else None
                answer, references = scenario_answer or self.generator.generate(
                    retrieval_question if context_used else question, hits, comparison=comparison,
                )
                refused = not bool(references)
                reason = "Insufficient grounded context" if refused else ""
                if use_ai and not refused:
                    try:
                        answer = self.llm.rewrite(question, answer, references, hits=hits)
                        ai_status = "on"
                    except LLMError as exc:
                        ai_status = "fallback"
                        reason = str(exc)
        response = Response(
            query=question, answer=answer, references=references, confidence=confidence,
            refused=refused, refusal_reason=reason, intent=intent.value, retrieved=hits,
            audio_url=None, providers={"retrieval": ("bm25" if hits and not using_semantic else self.searcher.provider), "voice": "browser", "llm": ai_status},
            timing={"total_ms": (time.perf_counter() - started) * 1000}, session_id=session_id,
            metadata={"grounded": bool(references), "ai_mode": ai_status, "lexical_coverage": round(lexical_coverage if 'lexical_coverage' in locals() else 0.0, 4)},
            card=build_card(answer, references, hits, confidence, best_suggestions(question, self._suggestion_topics) if refused else None),
        )
        if record_session and not refused and references and intent == Intent.ACADEMIC_RULES:
            self.session.add_turn(
                session_id, question, answer, intent.value, references[0].aid, references[0].rid,
                context_question=context_question, context_root=context_root,
                response=response.to_dict(),
            )
        # Also discard greetings/refusals and non-recorded replies if deletion
        # completed during retrieval or generation.
        self.ensure_session_open(session_id)
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
        return self.add_documents([{
            "filename": filename, "content": content, "use_ocr": use_ocr, "metadata": metadata,
        }])["items"][0]

    def add_documents(self, uploads: list[dict]) -> dict:
        with self.documents.adding_many(uploads) as items:
            stats, searcher = build_index(self.config, return_searcher=True)
        self.searcher = searcher
        return {"items": items, "index": stats}

    def remove_document(self, item_id: str) -> None:
        self.remove_documents([item_id])

    def remove_documents(self, item_ids: list[str]) -> dict:
        with self.documents.removing_many(item_ids) as result:
            stats, searcher = build_index(self.config, return_searcher=True)
            self.searcher = searcher
        return {**result, "index": stats}

    def update_document_date(self, item_id: str, document_date: str) -> dict:
        with self.documents.change_date(item_id, document_date) as item:
            _, searcher = build_index(self.config, return_searcher=True)
        self.searcher = searcher
        return item

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

    def history(self, session_id: str, *, owner: str | None = None) -> list[dict]:
        return self.session.get_history(session_id, self.config.max_history, owner=owner)

    def authorize_session(self, session_id: str, owner: str, *, create: bool = False):
        self.session.authorize(session_id, owner, create=create)

    def list_conversations(self, owner: str) -> list[dict]:
        return self.session.list_conversations(owner)

    def delete_history(self, session_id: str) -> int:
        return self.session.delete_history(session_id)

    def ensure_session_open(self, session_id: str):
        self.session.ensure_open(session_id)

    def history_status(self, session_id: str, *, owner: str | None = None) -> dict:
        return {"session_id": session_id, "closed": self.session.is_closed(session_id, owner=owner)}
