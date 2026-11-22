"""Application orchestration for the grounded academic-regulation assistant."""
from __future__ import annotations

import time
import threading
from datetime import date
from pathlib import Path

from .classifier import Classifier, Intent
from .cards import best_suggestions, build_card, build_suggestion_topics
from .corpus import build_corpus
from .documents import DocumentRepository
from .document_overview import answer_overview, overview_card, overview_request
from .generator import DECLINE_MSG, Generator
from .index_version import index_fingerprint
from .llm import GroundedLLM, LLMError
from .models import Regulation, Response
from .nlp import normalize, strip_accents
from .question_focus import question_focus
from .regulation_queries import answer_metadata
from .searcher import HybridSearcher, StaleIndexError
from .scenarios import comparison_subjects, comparison_topic, expand_retrieval_query, is_attendance_training_scenario, is_comparison_query, is_context_dependent, is_contextual_follow_up, is_historical_query, is_underspecified_follow_up, is_version_comparison_query
from .storage_backend import document_repository, session_store, writing, storage_backend
from .persistent_documents import rollback_index
from .settings import DOCS, INDEX_JSON, SESSION_DB, AppConfig
from .splitter import split_regulation


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
    def __init__(self, config: AppConfig, searcher: HybridSearcher, *, documents=None):
        self.config = config
        self.searcher = searcher
        self.classifier = Classifier()
        self.generator = Generator(config)
        self.llm = GroundedLLM(config)
        self.session = session_store(SESSION_DB)
        self.documents = documents if documents is not None else document_repository(DOCS)
        self._corpus_lock = threading.RLock()
        self._indexed_revision = getattr(self.documents, "revision", None)
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
        repository = document_repository(DOCS)
        with rollback_index(repository, index_path), writing(repository):
            searcher = cls._load_searcher(config, index_path)
            return cls(config, searcher, documents=repository)

    @staticmethod
    def _load_searcher(config, index_path):
        if index_path.exists():
            try:
                searcher = HybridSearcher.load(
                    str(index_path), config,
                    article_version=DocumentRepository.article_build_version(),
                    index_fingerprint=index_fingerprint(config, DOCS),
                )
                return searcher
            except StaleIndexError as exc:
                print(f"Rebuilding search index: {exc}")
        _, searcher = build_index(config, return_searcher=True, index_path=index_path)
        return searcher

    def _refresh_corpus(self):
        """Other processes may have committed a new durable document revision."""
        repository = self.documents
        if not getattr(repository, "durable", False):
            return
        if repository.state.revision() != self._indexed_revision:
            with self._corpus_lock:
                if repository.state.revision() != self._indexed_revision:
                    with rollback_index(repository, INDEX_JSON), writing(repository):
                        _, searcher = build_index(self.config, return_searcher=True)
                    self.searcher = searcher
                    self._indexed_revision = repository.revision

    def _recent_grounded_history(self, session_id: str) -> list[dict]:
        try:
            rows = self.session.get_history(session_id, 3)
        except Exception:
            return []
        return [
            row for row in rows
            if row.get("intent") == Intent.ACADEMIC_RULES.value and not row.get("refused")
        ]

    def _retrieve_and_generate(
        self,
        question: str,
        session_id: str,
        ref_date: str | None = None,
        use_context: bool = True,
    ) -> dict:
        intent = self.classifier.classify(question)
        refused, reason, references, hits, confidence = False, "", [], [], 0.0
        using_semantic = False
        lexical_coverage = 0.0
        context_question = context_root = question
        is_overview = False

        if not question:
            answer, refused, reason = "Bạn hãy nhập câu hỏi về quy chế đào tạo.", True, "Empty question"
        elif intent == Intent.GREETING:
            answer, confidence = "Chào bạn! Tôi hỗ trợ tra cứu quy chế đào tạo. Bạn có thể hỏi về tín chỉ, đăng ký học phần, bảo lưu, tốt nghiệp hoặc học vụ.", 1.0
        elif intent == Intent.THANKS:
            q_ascii = strip_accents(normalize(question)).lower()
            if "tam biet" in q_ascii or "bye" in q_ascii:
                answer = "Chào tạm biệt bạn! Khi nào cần tra cứu quy chế đào tạo, bạn cứ quay lại hỏi tôi nhé."
            else:
                answer = "Không có gì! Nếu bạn cần tra cứu thêm quy định học vụ nào khác, cứ nói hoặc nhập câu hỏi nhé."
            confidence = 1.0
        elif intent == Intent.TOXIC:
            answer, refused, reason = "Tôi chỉ hỗ trợ các câu hỏi về quy chế đào tạo trong môi trường an toàn.", True, "Unsafe request"
        elif overview_request(question):
            is_overview = True
            answer, references, hits, confidence = answer_overview(
                overview_request(question), self.searcher, ref_date or date.today().isoformat(),
            )
            refused = not bool(references)
            reason = "Insufficient grounded context" if refused else ""
        elif question_focus(question).kind.startswith("metadata_") and not is_comparison_query(question):
            answer, references, hits, confidence = answer_metadata(
                question_focus(question), self.searcher, ref_date or date.today().isoformat(),
            )
            refused = not bool(references)
            reason = "Insufficient grounded context" if refused else ""
        else:
            scenario = is_attendance_training_scenario(question)
            comparison = is_comparison_query(question)
            version_comparison = is_version_comparison_query(question)
            subjects = comparison_subjects(question) if comparison and not version_comparison else ()
            historical = version_comparison or is_historical_query(question)
            retrieval_question = expand_retrieval_query(comparison_topic(question) if comparison else question)
            is_follow_up = is_contextual_follow_up(question)
            underspecified = is_underspecified_follow_up(question)
            retrieval_limit = max(self.config.top_k, 20)
            today_str = ref_date or date.today().isoformat()

            def retrieve(query):
                return self.searcher.rerank_by_coverage(
                    query, self.searcher.search(
                        query, retrieval_limit, today_str, include_expired=historical,
                    ),
                )

            def evaluate_gate(r_query, r_hits, *, ctx_used: bool):
                sem = any(hit.vec != 0 for hit in r_hits)
                lex = self.searcher.lexical_coverage(question_focus(r_query).topic, r_hits)
                conf = min(1.0, r_hits[0].score) if sem and r_hits else lex
                fl = self.config.semantic_floor if sem else self.config.lexical_coverage_floor
                if scenario and not sem:
                    fl = min(fl, 0.30)
                if (is_follow_up or underspecified) and ctx_used and not sem:
                    fl = min(fl, 0.40)
                spec = self.searcher.has_specific_evidence(r_query, r_hits)
                return sem, lex, conf, fl, spec

            hits = retrieve(retrieval_question)
            if subjects:
                by_id = {(hit.chunk.rid, hit.chunk.cid): hit for hit in hits}
                for subject in subjects:
                    for hit in retrieve(expand_retrieval_query(subject)):
                        by_id.setdefault((hit.chunk.rid, hit.chunk.cid), hit)
                hits = list(by_id.values())
            dependent = is_context_dependent(question)
            context_used = False
            if use_context and is_follow_up and dependent:
                context_q, root = self.session.contextualize(
                    session_id, retrieval_question, limit=self.config.max_history,
                )
                if context_q != retrieval_question:
                    context_hits = [hit for hit in retrieve(context_q) if self.searcher.has_root_topic(root, hit)]
                    if self.searcher.has_specific_evidence(context_q, context_hits):
                        hits, retrieval_question = context_hits, context_q
                        context_used = True
                        context_question, context_root = context_q, root
            elif use_context and not dependent and underspecified and not comparison:
                # Stage-3 grounded fallback: natural follow-up facets lacking a
                # named regulation subject try standalone first, then inherit
                # the recent root topic only if standalone evidence is absent.
                _, _, s_conf, s_floor, s_spec = evaluate_gate(retrieval_question, hits, ctx_used=False)
                if not hits or s_conf < s_floor or not s_spec:
                    context_q, root = self.session.contextualize(
                        session_id, retrieval_question, limit=self.config.max_history, force=True,
                    )
                    if context_q != retrieval_question and root:
                        context_hits = [hit for hit in retrieve(context_q) if self.searcher.has_root_topic(root, hit)]
                        if self.searcher.has_specific_evidence(context_q, context_hits):
                            hits, retrieval_question = context_hits, context_q
                            context_used = True
                            context_question, context_root = context_q, root
            if dependent and not context_used:
                hits = []
            if historical and not comparison:
                expired = [hit for hit in hits if hit.chunk.valid_until]
                hits = expired + [hit for hit in hits if not hit.chunk.valid_until]
            using_semantic, lexical_coverage, confidence, floor, specific_evidence = evaluate_gate(
                retrieval_question, hits, ctx_used=context_used,
            )
            if comparison and not version_comparison:
                selected = self.generator.select_comparison_evidence(question, hits)
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
                floor = 0.0
            if not hits or confidence < floor or not specific_evidence:
                answer, refused, reason = DECLINE_MSG, True, "Insufficient grounded context"
            else:
                scenario_answer = self.generator.generate_attendance_training_scenario(hits, question) if scenario else None
                answer, references = scenario_answer or self.generator.generate(
                    retrieval_question if context_used else question, hits, comparison=comparison,
                )
                refused = not bool(references)
                reason = "Insufficient grounded context" if refused else ""

        return {
            "question": question,
            "intent": intent,
            "answer": answer,
            "refused": refused,
            "reason": reason,
            "references": references,
            "hits": hits,
            "confidence": confidence,
            "using_semantic": using_semantic,
            "lexical_coverage": lexical_coverage,
            "context_question": context_question,
            "context_root": context_root,
            "is_overview": is_overview,
        }

    def _build_response(self, state: dict, *, session_id: str, started: float, ai_status: str, record_session: bool) -> Response:
        question = state["question"]
        answer = state["answer"]
        references = state["references"]
        hits = state["hits"]
        confidence = state["confidence"]
        refused = state["refused"]
        reason = state["reason"]
        intent = state["intent"]
        using_semantic = state["using_semantic"]
        lexical_coverage = state["lexical_coverage"]

        response = Response(
            query=question, answer=answer, references=references, confidence=confidence,
            refused=refused, refusal_reason=reason, intent=intent.value, retrieved=hits,
            audio_url=None, providers={"retrieval": ("bm25" if hits and not using_semantic else self.searcher.provider), "voice": "browser", "llm": ai_status},
            timing={"total_ms": (time.perf_counter() - started) * 1000}, session_id=session_id,
            metadata={"grounded": bool(references), "ai_mode": ai_status, "lexical_coverage": round(lexical_coverage, 4)},
            card=(
                overview_card(answer, references, hits, confidence)
                if state["is_overview"] and not refused
                else build_card(
                    answer, references, hits, confidence,
                    best_suggestions(question, self._suggestion_topics) if refused else None,
                    llm_rewritten=(ai_status == "on"),
                )
            ),
        )
        if record_session and not refused and references and intent == Intent.ACADEMIC_RULES:
            self.session.add_turn(
                session_id, question, answer, intent.value, references[0].aid, references[0].rid,
                context_question=state["context_question"], context_root=state["context_root"],
                response=response.to_dict(),
            )
        # Also discard greetings/refusals and non-recorded replies if deletion
        # completed during retrieval or generation.
        self.ensure_session_open(session_id)
        return response

    def ask(self, question: str, session_id: str, ref_date: str | None = None, with_audio: bool = False, use_context: bool = True, use_ai: bool = False, record_session: bool = True) -> Response:
        started = time.perf_counter()
        self._refresh_corpus()
        self.ensure_session_open(session_id)
        question = (question or "").strip()
        state = self._retrieve_and_generate(question, session_id, ref_date=ref_date, use_context=use_context)
        ai_status = "off"
        if use_ai and not state["refused"] and state["references"] and state["intent"] == Intent.ACADEMIC_RULES and not state["is_overview"]:
            try:
                history_summary = self._recent_grounded_history(session_id) if use_context else None
                state["answer"] = self.llm.rewrite(
                    question, state["answer"], state["references"], hits=state["hits"],
                    history_summary=history_summary,
                )
                ai_status = "on"
            except LLMError as exc:
                ai_status = "fallback"
                state["reason"] = str(exc)
        return self._build_response(state, session_id=session_id, started=started, ai_status=ai_status, record_session=record_session)

    def stream_ask(self, question: str, session_id: str, ref_date: str | None = None, use_context: bool = True, use_ai: bool = False, record_session: bool = True):
        """Yield SSE-ready events: evidence -> delta* -> done."""
        started = time.perf_counter()
        self._refresh_corpus()
        self.ensure_session_open(session_id)
        question = (question or "").strip()
        state = self._retrieve_and_generate(question, session_id, ref_date=ref_date, use_context=use_context)
        yield {
            "event": "evidence",
            "data": {
                "references": [ref.to_dict() for ref in state["references"]],
                "refused": state["refused"],
                "intent": state["intent"].value,
                "streaming_ai": bool(
                    use_ai and self.llm.configured and not state["refused"]
                    and state["references"] and state["intent"] == Intent.ACADEMIC_RULES and not state["is_overview"]
                ),
            },
        }
        ai_status = "off"
        if use_ai and not state["refused"] and state["references"] and state["intent"] == Intent.ACADEMIC_RULES and not state["is_overview"]:
            if not self.llm.configured:
                ai_status = "fallback"
                state["reason"] = "Chế độ AI chưa được cấu hình API key."
            else:
                chunks: list[str] = []
                try:
                    history_summary = self._recent_grounded_history(session_id) if use_context else None
                    for delta in self.llm.stream_rewrite(
                        question, state["answer"], state["references"], history_summary=history_summary,
                    ):
                        chunks.append(delta)
                        yield {"event": "delta", "data": {"text": delta}}
                    rewritten = "".join(chunks).strip()
                    if rewritten:
                        state["answer"] = rewritten
                        ai_status = "on"
                    else:
                        ai_status = "fallback"
                        state["reason"] = "Mô hình AI không trả về nội dung hợp lệ; đã dùng câu trả lời từ tài liệu."
                except LLMError as exc:
                    ai_status = "fallback"
                    state["reason"] = str(exc)
        response = self._build_response(state, session_id=session_id, started=started, ai_status=ai_status, record_session=record_session)
        yield {"event": "done", "data": response.to_dict()}

    def suggestion_topics(self) -> list[dict]:
        return self._suggestion_topics

    def list_documents(self) -> list[dict]:
        self._refresh_corpus()
        with self._corpus_lock:
            return self._list_documents()

    def _list_documents(self) -> list[dict]:
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
        with self._corpus_lock, rollback_index(self.documents, INDEX_JSON):
            with self.documents.adding_many(uploads) as items:
                stats, searcher = build_index(self.config, return_searcher=True)
            self.searcher = searcher
            self._indexed_revision = getattr(self.documents, "revision", None)
        return {"items": items, "index": stats}

    def remove_document(self, item_id: str) -> None:
        self.remove_documents([item_id])

    def remove_documents(self, item_ids: list[str]) -> dict:
        with self._corpus_lock, rollback_index(self.documents, INDEX_JSON):
            with self.documents.removing_many(item_ids) as result:
                stats, searcher = build_index(self.config, return_searcher=True)
            self.searcher = searcher
            self._indexed_revision = getattr(self.documents, "revision", None)
        return {**result, "index": stats}

    def update_document_date(self, item_id: str, document_date: str) -> dict:
        with self._corpus_lock, rollback_index(self.documents, INDEX_JSON):
            with self.documents.change_date(item_id, document_date) as item:
                _, searcher = build_index(self.config, return_searcher=True)
            self.searcher = searcher
            self._indexed_revision = getattr(self.documents, "revision", None)
        return item

    def document_text(self, item_id: str) -> dict:
        self._refresh_corpus()
        with self._corpus_lock:
            result = self.documents.get_text(item_id)
            item = next((entry for entry in self.documents.list() if entry["id"] == item_id), None)
            result["chunk_count"] = sum(1 for chunk in self.searcher.chunks if item and chunk.rid == item["rid"])
            return result

    def rebuild_index(self) -> dict:
        with self._corpus_lock:
            with rollback_index(self.documents, INDEX_JSON), writing(self.documents):
                result, searcher = build_index(self.config, return_searcher=True)
            self.searcher = searcher
            self._indexed_revision = getattr(self.documents, "revision", None)
        return result

    def storage_status(self) -> dict:
        self._refresh_corpus()
        return {
            "backend": storage_backend(),
            "persistent": getattr(self.documents, "durable", False),
            "document_revision": getattr(self.documents, "revision", None),
        }

    def backup_storage(self) -> dict:
        from .storage_transfer import backup_local, backup_persistent
        with self._corpus_lock:
            if getattr(self.documents, "durable", False):
                result = backup_persistent(self.documents)
            else:
                result = backup_local(SESSION_DB.parent)
        # Do not expose filesystem paths or the private backup's object key.
        return {
            "filename": Path(result["path"]).name,
            "documents": result["documents"], "turns": result["turns"],
            "persistent_copy": bool(result.get("backup_key")),
        }

    def public_document(self, rid: str) -> dict | None:
        """Return sanitized public regulation articles from indexed chunks only.

        Never exposes admin filenames, filesystem paths, hashes, or OCR flags.
        """
        self._refresh_corpus()
        with self._corpus_lock:
            doc_chunks = [chunk for chunk in self.searcher.chunks if chunk.rid == rid]
            if not doc_chunks:
                return None
            doc_meta = next((doc for doc in self._list_documents() if doc.get("rid") == rid), None)
            articles: list[dict] = []
            by_aid: dict[str, dict] = {}
            for chunk in doc_chunks:
                entry = by_aid.get(chunk.aid)
                body = self.searcher._clause_body(chunk).strip()
                if entry is None:
                    entry = {
                        "aid": chunk.aid,
                        "heading": chunk.art_heading,
                        "clauses": [body] if body else [],
                    }
                    by_aid[chunk.aid] = entry
                    articles.append(entry)
                elif body and body not in entry["clauses"]:
                    entry["clauses"].append(body)
            first = doc_chunks[0]
            return {
                "rid": first.rid,
                "title": first.reg_title,
                "version": (doc_meta or {}).get("version") or first.version,
                "valid_from": (doc_meta or {}).get("valid_from") or first.valid_from,
                "valid_until": (doc_meta or {}).get("valid_until") if doc_meta is not None else first.valid_until,
                "kind": (doc_meta or {}).get("kind", "demo"),
                "articles": [
                    {
                        "aid": art["aid"],
                        "heading": art["heading"],
                        "text": "\n".join(art["clauses"]),
                    }
                    for art in articles
                ],
            }

    def list_sources(self) -> list[dict]:
        return [chunk.to_dict() for chunk in self.searcher.chunks]

    def history(
        self,
        session_id: str,
        *,
        owner: str | None = None,
        limit: int | None = None,
        before_id: int | None = None,
    ) -> list[dict]:
        # Decouple UI display history (default 100 turns) from RAG context
        # window (config.max_history = 8 used in session.contextualize).
        display_limit = 100 if limit is None else max(1, min(int(limit), 200))
        if before_id is not None:
            return self.session.get_history(session_id, display_limit, owner=owner, before_id=before_id)
        return self.session.get_history(session_id, display_limit, owner=owner)

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
