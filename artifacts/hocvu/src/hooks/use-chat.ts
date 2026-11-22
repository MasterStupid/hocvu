import { useCallback, useEffect, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ApiError, api, describeError, isAbort, type AnswerCard, type AskResponse, type Conversation, type HistoryRow, type Reference } from '@/lib/api';
import { DELETED_STORAGE_KEY, announceDeletion, ownerKey, storeSessionId, storedSessionId, uuid } from '@/lib/identity';

export type Presentation = 'answer' | 'refusal' | 'greeting' | 'legacy';
export interface Answer {
  text: string;
  references: Reference[];
  card: AnswerCard;
  intent: string;
  refused: boolean | null;
  refusalReason: string;
  presentation: Presentation;
  restored: boolean;
  providers?: Record<string, string>;
}
export interface ChatTurn {
  key: string;
  question: string;
  status: 'pending' | 'done' | 'error';
  answer?: Answer;
  error?: string;
}
export type Notice = { tone: 'info' | 'ok' | 'warn' | 'error'; text: string } | null;
export type RestoreState = { state: 'loading' | 'ready' | 'failed'; error?: string };

export const conversationsKey = ['conversations'] as const;

function hasSavedEvidence(r: { refused: boolean | null; references: Reference[] | null; card: AnswerCard | null }) {
  const g = r.card?.grounding;
  return typeof r.refused === 'boolean' && Array.isArray(r.references) && !!g
    && Number.isFinite(g.level) && Number.isFinite(g.source_count) && typeof g.label === 'string';
}

export function fromResponse(res: AskResponse): Answer {
  return {
    text: res.answer, references: res.references || [], card: res.card || {}, intent: res.intent,
    refused: res.refused, refusalReason: res.refusal_reason || '', restored: false, providers: res.providers,
    presentation: res.refused ? 'refusal' : res.intent === 'greeting' ? 'greeting' : 'answer',
  };
}

export function fromRow(row: HistoryRow): ChatTurn {
  // Old engine rows used empty source IDs for academic refusals (legacy parity).
  const legacyRefusal = row.intent === 'unsafe' || (row.intent === 'academic_rules' && row.article_id === '' && row.rid === '');
  const refused = typeof row.refused === 'boolean' ? row.refused : legacyRefusal ? true : null;
  const normalized = { refused, references: row.references, card: row.card };
  const presentation: Presentation = refused ? 'refusal' : row.intent === 'greeting' ? 'greeting' : hasSavedEvidence(normalized) ? 'answer' : 'legacy';
  // Saved with the answer itself; older rows have no recorded wording mode.
  const mode = row.card?.answer_mode;
  const providers = mode === 'on' || mode === 'off' || mode === 'fallback' ? { llm: mode } : undefined;
  return {
    key: `row-${row.id ?? uuid()}`, question: row.question, status: 'done',
    answer: {
      text: row.answer, references: row.references || [], card: row.card || {}, intent: row.intent || 'other',
      refused, refusalReason: row.refusal_reason || '', presentation, restored: true, providers,
    },
  };
}

export function useConversations() {
  return useQuery({
    queryKey: conversationsKey,
    queryFn: async ({ signal }) => {
      const list = await api.conversations(ownerKey(), signal);
      if (!Array.isArray(list)) throw new Error('Danh sách hội thoại không hợp lệ.');
      return list;
    },
    retry: 1,
  });
}

export function useChat() {
  const qc = useQueryClient();
  const [sessionId, setSessionId] = useState<string>(() => storedSessionId() || uuid());
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [restore, setRestore] = useState<RestoreState>({ state: 'loading' });
  const [sending, setSending] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [notice, setNotice] = useState<Notice>(null);

  const version = useRef(0);
  const sessionRef = useRef(sessionId);
  const closed = useRef(new Set<string>());
  const abortRef = useRef<AbortController | null>(null);

  const freshId = useCallback(() => {
    let id = uuid();
    while (closed.current.has(id)) id = uuid();
    return id;
  }, []);

  const resetTo = useCallback((id: string) => {
    version.current += 1;
    abortRef.current?.abort();
    abortRef.current = null;
    sessionRef.current = id;
    storeSessionId(id);
    setSessionId(id);
    setTurns([]);
    setSending(false);
    setDeleting(false);
    setRestore({ state: 'ready' });
    return version.current;
  }, []);

  const dropFromList = useCallback((id: string) => {
    qc.setQueryData<Conversation[]>(conversationsKey, (old) => old?.filter((c) => c.session_id !== id));
  }, [qc]);

  const forget = useCallback((id: string, message?: string) => {
    closed.current.add(id);
    dropFromList(id);
    if (id !== sessionRef.current) return;
    resetTo(freshId());
    setNotice({ tone: 'info', text: message || 'Hội thoại này đã bị xóa. Một hội thoại mới đã sẵn sàng.' });
  }, [dropFromList, freshId, resetTo]);

  const open = useCallback(async (id: string) => {
    if (closed.current.has(id)) { forget(id); return; }
    const v = resetTo(id);
    setRestore({ state: 'loading' });
    setNotice(null);
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      const owner = ownerKey();
      const [rows, status] = await Promise.all([
        api.history(owner, id, ctrl.signal), api.historyStatus(owner, id, ctrl.signal),
      ]);
      if (v !== version.current) return;
      if (status.closed === true) { forget(id); return; }
      if (!Array.isArray(rows)) throw new Error('Lịch sử hội thoại không hợp lệ.');
      setTurns(rows.map(fromRow));
      setRestore({ state: 'ready' });
    } catch (e) {
      if (v !== version.current || isAbort(e)) return;
      if (e instanceof ApiError && e.code === 'session_unavailable') {
        resetTo(freshId());
        setNotice({ tone: 'warn', text: 'Trình duyệt này không có quyền mở hội thoại cũ. Đã mở hội thoại mới; bản lưu cũ không bị xóa.' });
        void qc.invalidateQueries({ queryKey: conversationsKey });
        return;
      }
      // Never send into hidden context after a failed restore.
      setRestore({ state: 'failed', error: describeError(e) });
    }
  }, [forget, freshId, qc, resetTo]);

  const retryRestore = useCallback(() => { void open(sessionRef.current); }, [open]);

  const newChat = useCallback(() => {
    if (deleting) return;
    resetTo(freshId());
    setNotice(null);
  }, [deleting, freshId, resetTo]);

  // Initial restore of the stored session.
  const booted = useRef(false);
  useEffect(() => {
    if (booted.current) return;
    booted.current = true;
    void open(sessionRef.current);
  }, [open]);

  type SendResult = { ok: true; answer: Answer } | { ok: false; restoreText?: string };
  const ask = useCallback(async (question: string, opts: { refDate: string; useAi: boolean }): Promise<SendResult> => {
    const q = question.trim();
    if (!q || sending || deleting || restore.state !== 'ready') return { ok: false, restoreText: question };
    const v = version.current;
    const id = sessionRef.current;
    const key = uuid();
    setTurns((t) => [...t, { key, question: q, status: 'pending' }]);
    setSending(true);
    setNotice(null);
    try {
      const res = await api.ask(ownerKey(), {
        question: q, session_id: id, ref_date: opts.refDate || null, use_ai: opts.useAi, with_audio: false,
      });
      void qc.invalidateQueries({ queryKey: conversationsKey });
      if (v !== version.current) return { ok: false };
      const answer = fromResponse(res);
      setTurns((t) => t.map((x) => (x.key === key ? { ...x, status: 'done', answer } : x)));
      return { ok: true, answer };
    } catch (e) {
      if (v !== version.current) return { ok: false };
      if (e instanceof ApiError && e.status === 410 && e.code === 'session_closed' && (!e.sessionId || e.sessionId === id)) {
        forget(id, 'Hội thoại này đã bị xóa ở nơi khác nên câu hỏi chưa được gửi. Câu hỏi đã được đặt lại vào ô nhập trong hội thoại mới.');
        return { ok: false, restoreText: q };
      }
      if (e instanceof ApiError && e.code === 'session_unavailable') {
        resetTo(freshId());
        setNotice({ tone: 'warn', text: 'Không có quyền truy cập hội thoại cũ. Đã mở hội thoại mới; bản lưu cũ không bị xóa.' });
        return { ok: false, restoreText: q };
      }
      setTurns((t) => t.map((x) => (x.key === key ? { ...x, status: 'error', error: describeError(e) } : x)));
      return { ok: false };
    } finally {
      if (v === version.current) setSending(false);
    }
  }, [deleting, forget, freshId, qc, resetTo, restore.state, sending]);

  const dismissTurn = useCallback((key: string) => setTurns((t) => t.filter((x) => x.key !== key)), []);

  const deleteCurrent = useCallback(async () => {
    if (sending || deleting || restore.state === 'loading') return false;
    const id = sessionRef.current;
    const v = version.current;
    const next = freshId();
    setDeleting(true);
    try {
      await api.deleteHistory(ownerKey(), id);
      closed.current.add(id);
      dropFromList(id);
      void qc.invalidateQueries({ queryKey: conversationsKey });
      announceDeletion(id);
      if (v === version.current) {
        resetTo(next);
        setNotice({ tone: 'ok', text: 'Đã xóa vĩnh viễn lịch sử hội thoại. Hội thoại mới đã sẵn sàng.' });
      }
      return true;
    } catch (e) {
      // Keep id, turns and sources intact so a failed request is retryable.
      if (v === version.current) {
        setNotice({ tone: 'error', text: `Chưa thể xác nhận xóa lịch sử: ${describeError(e)}` });
        setDeleting(false);
      }
      return false;
    }
  }, [deleting, dropFromList, freshId, qc, resetTo, restore.state, sending]);

  // Cross-tab deletion notices and server-side closure checks.
  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key !== DELETED_STORAGE_KEY || !e.newValue) return;
      try {
        const n = JSON.parse(e.newValue) as { sessionId?: unknown };
        if (typeof n.sessionId === 'string') forget(n.sessionId);
      } catch { /* ignore */ }
    };
    const check = async () => {
      if (document.visibilityState !== 'visible') return;
      const id = sessionRef.current; const v = version.current;
      try {
        const s = await api.historyStatus(ownerKey(), id);
        if (v === version.current && s.session_id === id && s.closed === true) forget(id);
      } catch { /* keep current view */ }
      void qc.invalidateQueries({ queryKey: conversationsKey });
    };
    window.addEventListener('storage', onStorage);
    window.addEventListener('focus', check);
    document.addEventListener('visibilitychange', check);
    return () => {
      window.removeEventListener('storage', onStorage);
      window.removeEventListener('focus', check);
      document.removeEventListener('visibilitychange', check);
    };
  }, [forget, qc]);

  useEffect(() => () => abortRef.current?.abort(), []);

  return {
    sessionId, turns, restore, sending, deleting, notice, setNotice,
    open, retryRestore, newChat, ask, dismissTurn, deleteCurrent,
    canSend: restore.state === 'ready' && !sending && !deleting,
  };
}

/* ---------- Export (same structure as legacy transcript export) ---------- */
function exportAnswer(a: Answer): string[] {
  if (a.presentation === 'greeting') return ['Trạng thái: Lời chào — không sử dụng căn cứ.', a.text];
  if (a.presentation === 'refusal') return ['Trạng thái: Từ chối trả lời — chưa đủ căn cứ.', a.text, ...(a.refusalReason ? [`Lý do từ chối: ${a.refusalReason}`] : [])];
  if (a.presentation === 'legacy') return ['Trạng thái: Lượt đã lưu — chi tiết căn cứ không có trong bản lưu này.', a.text];
  const segs = a.card.verdict_segments?.length ? a.card.verdict_segments : [{ text: a.text, cites: [] }];
  const g = a.card.grounding;
  return [
    ...segs.map((s) => [s.text, ...(s.cites || []).map((c) => `[${c}]`)].join(' ')),
    ...(g ? [`Căn cứ ${g.label} · ${g.source_count} nguồn · Mức ${g.level}/5`] : []),
    ...(a.card.notes?.length ? ['Lưu ý:', ...a.card.notes.map((n) => n.text)] : []),
    ...(a.references.length ? [
      'Nguồn của lượt này (số [n] chỉ áp dụng trong lượt):',
      ...a.references.flatMap((r, i) => [
        `Nguồn [${i + 1}]: ${r.reg_title || ''}`,
        ...(r.rid ? [`Mã văn bản: ${r.rid}`] : []), ...(r.version ? [`Phiên bản: ${r.version}`] : []),
        ...(r.aid ? [`Điều/mục: ${r.aid}`] : []), ...(r.art_heading ? [`Tiêu đề: ${r.art_heading}`] : []),
        ...(r.clause_ids?.length ? [`Khoản: ${r.clause_ids.join(', ')}`] : []),
        'Trích dẫn:', r.excerpt || '', '',
      ]),
    ] : []),
  ];
}

export function exportTranscript(turns: ChatTurn[]): string {
  let n = 0;
  return [
    'HOCVU AI — LỊCH SỬ HỘI THOẠI', `Xuất lúc: ${new Date().toLocaleString('vi-VN')}`, '',
    ...turns.filter((t) => t.status === 'done' && t.answer).flatMap((t) => [
      'BẠN:', t.question, '', `HOCVU AI (lượt ${++n}):`, ...exportAnswer(t.answer as Answer), '',
    ]),
  ].join('\n');
}

export const citeLabel = (r: Reference) => `${r.aid || 'Nguồn'}, ${r.clause_ids?.length ? `Khoản ${r.clause_ids.join(', ')}` : 'nội dung liên quan'}`;

export function answerMarkdown(a: Answer): string {
  const segs = a.card.verdict_segments?.length ? a.card.verdict_segments : [{ text: a.text, cites: [] }];
  return [segs.map((s) => s.text).join('\n\n'), '', ...a.references.map((r, i) => `Nguồn [${i + 1}]: ${citeLabel(r)} — ${r.reg_title}\n${r.excerpt}`)].join('\n');
}

export function answerSpeech(a: Answer): string {
  const segs = a.card.verdict_segments?.length ? a.card.verdict_segments : [{ text: a.text }];
  return segs.map((s) => s.text).join('. ');
}
