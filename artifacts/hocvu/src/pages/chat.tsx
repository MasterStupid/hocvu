import { useCallback, useEffect, useRef, useState } from 'react';
import { useLocation, useSearch } from 'wouter';
import { AnimatePresence, motion } from 'framer-motion';
import { AlertTriangle, Download, History, Info, Loader2, Mic, Radio, RotateCw, Square, Trash2, Volume2, VolumeX, X } from 'lucide-react';
import { Sheet, SheetContent, SheetDescription, SheetTitle } from '@/components/ui/sheet';
import { AnswerCard } from '@/components/chat/answer-card';
import { Composer } from '@/components/chat/composer';
import { ConversationList } from '@/components/chat/conversation-list';
import { RichText } from '@/components/chat/rich-text';
import { Welcome } from '@/components/chat/welcome';
import { ConfirmDialog } from '@/components/confirm-dialog';
import { NoticeBar } from '@/components/states';
import { answerSpeech, exportTranscript, useChat, useConversations } from '@/hooks/use-chat';
import { useHealth } from '@/hooks/use-public';
import { useSpeaker } from '@/hooks/use-voice';
import { useVoiceSession } from '@/hooks/use-voice-session';
import { useToast } from '@/hooks/use-toast';
import { usePrefs } from '@/lib/prefs';
import { downloadBlob, todayISO } from '@/lib/format';
import { cn } from '@/lib/utils';

const LIVE_LABELS = {
  off: '',
  listening: 'Hội thoại Live · Đang lắng nghe',
  confirming: 'Hội thoại Live · Đang chuẩn bị gửi',
  thinking: 'Hội thoại Live · Đang tra cứu quy chế…',
  speaking: 'Hội thoại Live · Đang đọc câu trả lời',
  paused: 'Hội thoại Live · Tạm dừng (bấm micro để nói tiếp)',
} as const;

export default function ChatPage() {
  const chat = useChat();
  const prefs = usePrefs();
  const health = useHealth();
  const { toast } = useToast();
  const speaker = useSpeaker(prefs.voice, prefs.rate);
  const conversations = useConversations();
  const [draft, setDraft] = useState('');
  const [refDate, setRefDate] = useState('');
  const [listOpen, setListOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<{ id: string; title: string } | null>(null);
  const [demoDismissed, setDemoDismissed] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);
  const search = useSearch();
  const [, navigate] = useLocation();

  // Prefill from /?q=... (used by the Library page), then clean the URL.
  useEffect(() => {
    const q = new URLSearchParams(search).get('q');
    if (q) { setDraft(q.slice(0, 4000)); navigate('/', { replace: true }); }
  }, [search, navigate]);

  useEffect(() => { bottom.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }); }, [chat.turns.length, chat.sending]);

  // Stop audio when switching conversation.
  const stopRef = useRef(speaker.stop);
  stopRef.current = speaker.stop;
  useEffect(() => { stopRef.current(); }, [chat.sessionId]);

  useEffect(() => {
    if (speaker.error) { toast({ title: 'Không phát được giọng đọc', description: speaker.error }); speaker.clearError(); }
  }, [speaker, toast]);

  // Read prefs at resolve time, not at send time, so disabling auto-read mid-flight is honored.
  const autoRef = useRef(prefs.autoSpeak);
  autoRef.current = prefs.autoSpeak;
  const [voiceRequest, setVoiceRequest] = useState(0);
  const [stopVoiceRequest, setStopVoiceRequest] = useState(0);

  const hasNativeMic = typeof window !== 'undefined' && !!((window as unknown as Record<string, unknown>).SpeechRecognition || (window as unknown as Record<string, unknown>).webkitSpeechRecognition);
  const hasRecorder = typeof window !== 'undefined' && typeof navigator !== 'undefined' && typeof navigator.mediaDevices?.getUserMedia === 'function' && typeof MediaRecorder !== 'undefined';
  const sttFallback = Boolean(health.data?.stt_fallback);
  const micSupported = hasNativeMic || (sttFallback && hasRecorder);
  const llmAvailable = health.isSuccess ? health.data.llm_available : undefined;
  const effectiveUseAi = llmAvailable === false ? false : prefs.aiEnabled;

  const sendRef = useRef<(text: string) => Promise<void>>(async () => {});
  const voiceSession = useVoiceSession({
    supported: micSupported,
    canSend: chat.canSend,
    sending: chat.sending,
    sessionId: chat.sessionId,
    speaker,
    onRequestListen: () => setVoiceRequest((n) => n + 1),
    onStopListen: () => setStopVoiceRequest((n) => n + 1),
    onAutoSubmit: (text) => sendRef.current(text),
  });

  const toggleAuto = () => {
    const next = !prefs.autoSpeak;
    if (next) speaker.unlock();
    if (!next) speaker.stop();
    prefs.set('autoSpeak', next);
  };

  const send = useCallback(async (text: string) => {
    if (!chat.canSend || !text.trim()) return;
    if (autoRef.current || voiceSession.liveEnabled) speaker.unlock();
    speaker.stop();
    setDraft('');
    const res = await chat.ask(text, {
      refDate,
      useAi: effectiveUseAi,
      withAudio: false,
      voice: prefs.voice,
      rate: prefs.rate,
    });
    if (!res.ok) {
      if (res.restoreText) setDraft(res.restoreText);
      if (voiceSession.liveEnabled) voiceSession.scheduleNextListen(1200);
      return;
    }
    // Pass the actual turnKey (res.key) so AnswerCard's Nghe/Dừng button stays in sync.
    voiceSession.speakAnswer(res.key, answerSpeech(res.answer), {
      autoSpeak: autoRef.current,
      audioUrl: res.answer.audioUrl,
    });
  }, [chat, effectiveUseAi, prefs.rate, prefs.voice, refDate, speaker, voiceSession]);

  sendRef.current = send;

  const current = conversations.data?.find((c) => c.session_id === chat.sessionId);
  const doneTurns = chat.turns.filter((t) => t.status === 'done');
  const blockedReason = chat.restore.state === 'loading' ? 'Đang khôi phục hội thoại, vui lòng chờ…'
    : chat.restore.state === 'failed' ? 'Chưa khôi phục được hội thoại nên tạm khóa gửi câu hỏi.'
    : chat.deleting ? 'Đang xóa lịch sử…' : null;

  const exportChat = () => {
    if (!doneTurns.length) return;
    downloadBlob(new Blob([exportTranscript(chat.turns)], { type: 'text/plain;charset=utf-8' }), `hocvu-ai-${todayISO()}.txt`);
    toast({ title: 'Đã tải tệp hội thoại', description: 'Tệp văn bản gồm câu hỏi, kết luận và nguồn trích dẫn.' });
  };

  const openConversation = (id: string) => {
    setListOpen(false);
    if (id === chat.sessionId && chat.restore.state !== 'failed') return;
    setDraft('');
    void chat.open(id);
  };
  const newChat = () => {
    setListOpen(false);
    voiceSession.stopLive();
    setDraft('');
    chat.newChat();
  };

  const requestDelete = (id: string, title: string) => {
    setDeleteTarget({ id, title });
  };

  const list = (
    <ConversationList
      currentId={chat.sessionId}
      onOpen={openConversation}
      onNew={newChat}
      onDelete={requestDelete}
      disabled={chat.deleting}
    />
  );
  let answerIndex = 0;

  return (
    <div className="lg:grid lg:grid-cols-[288px_1fr] min-h-[calc(100dvh-3.5rem)] md:min-h-[100dvh]">
      <aside className="hidden lg:flex flex-col sticky top-0 h-[100dvh] border-r border-border bg-muted/30" aria-label="Hội thoại đã lưu">
        <div className="px-4 pt-5"><span className="kicker">Hội thoại đã lưu</span></div>
        {list}
      </aside>
      <Sheet open={listOpen} onOpenChange={setListOpen}>
        <SheetContent side="left" className="w-[300px] p-0 bg-background flex flex-col">
          <SheetTitle className="px-4 pt-5 font-serif text-xl">Hội thoại đã lưu</SheetTitle>
          <SheetDescription className="sr-only">Chọn hội thoại để mở lại</SheetDescription>
          {list}
        </SheetContent>
      </Sheet>

      <section className="flex flex-col min-h-[calc(100dvh-3.5rem)] md:min-h-[100dvh] min-w-0">
        <div className="sticky top-14 md:top-0 z-20 flex items-center gap-2 px-4 sm:px-8 h-14 border-b border-border bg-background/90 backdrop-blur">
          <button type="button" className="btn btn-ghost btn-sm lg:hidden -ml-2" onClick={() => setListOpen(true)} data-testid="button-open-conversations">
            <History /> <span className="hidden sm:inline">Hội thoại</span>
          </button>
          <h1 className="flex-1 min-w-0 truncate font-serif text-lg" data-testid="text-conversation-title">
            {current?.title || (chat.restore.state === 'loading' ? 'Đang mở hội thoại…' : 'Phiên tra cứu mới')}
          </h1>
          <button type="button" className="btn btn-ghost btn-sm" onClick={exportChat} disabled={!doneTurns.length || chat.deleting} data-testid="button-export">
            <Download /> <span className="hidden sm:inline">Xuất</span>
          </button>
          <button type="button" className="btn btn-danger-ghost btn-sm"
            onClick={() => requestDelete(chat.sessionId, current?.title || 'Phiên tra cứu hiện tại')}
            disabled={chat.sending || chat.deleting || chat.restore.state === 'loading'} data-testid="button-delete-history">
            <Trash2 /> <span className="hidden sm:inline">Xóa lịch sử</span>
          </button>
        </div>

        <div className="flex-1 px-4 sm:px-8">
          <div className="max-w-3xl mx-auto py-6 space-y-6" aria-live="polite">
            {health.data?.demo_only && !demoDismissed && (
              <div className="flex items-start gap-2.5 rounded-lg border border-ochre/35 bg-ochre/8 px-4 py-2.5 text-xs text-foreground" role="note" data-testid="banner-demo-corpus">
                <Info className="w-4 h-4 text-ochre shrink-0 mt-0.5" aria-hidden="true" />
                <p className="flex-1 leading-relaxed">
                  <strong>Kho dữ liệu minh họa:</strong> Hệ thống đang chạy trên {health.data.documents} văn bản mẫu để thử nghiệm. Hãy đối chiếu văn bản gốc với Phòng Đào tạo trước khi quyết định.
                </p>
                <button type="button" onClick={() => setDemoDismissed(true)} aria-label="Ẩn thông báo dữ liệu mẫu" className="p-0.5 text-muted-foreground hover:text-foreground">
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
            )}

            {chat.notice && <NoticeBar tone={chat.notice.tone} onClose={() => chat.setNotice(null)}>{chat.notice.text}</NoticeBar>}

            {chat.hasMoreHistory && (
              <div className="flex justify-center">
                <button type="button" className="btn btn-outline btn-sm" onClick={() => void chat.loadMore()} disabled={chat.loadingMore} data-testid="button-load-more">
                  {chat.loadingMore ? <><Loader2 className="animate-spin" /> Đang tải thêm…</> : 'Tải các lượt cũ hơn'}
                </button>
              </div>
            )}

            {chat.restore.state === 'loading' && (
              <div className="space-y-5 pt-4" aria-label="Đang khôi phục hội thoại">
                {[0, 1].map((i) => (
                  <div key={i} className="space-y-3">
                    <div className="ml-auto h-10 w-2/3 rounded-md bg-muted animate-pulse" />
                    <div className="h-40 rounded-md bg-muted/70 animate-pulse" />
                  </div>
                ))}
              </div>
            )}

            {chat.restore.state === 'failed' && (
              <div role="alert" className="paper margin-line pl-5 pr-4 py-4">
                <div className="flex gap-3">
                  <AlertTriangle className="w-5 h-5 text-seal shrink-0 mt-0.5" aria-hidden="true" />
                  <div className="flex-1">
                    <p className="font-medium">Chưa khôi phục được hội thoại</p>
                    <p className="text-sm text-muted-foreground mt-0.5">{chat.restore.error} Để tránh trả lời thiếu ngữ cảnh, việc gửi câu hỏi đang tạm khóa.</p>
                    <div className="flex flex-wrap gap-2 mt-3">
                      <button type="button" className="btn btn-outline btn-sm" onClick={chat.retryRestore} data-testid="button-retry-restore"><RotateCw /> Thử lại</button>
                      <button type="button" className="btn btn-ghost btn-sm" onClick={newChat} data-testid="button-restore-new">Mở hội thoại mới</button>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {chat.restore.state !== 'loading' && chat.turns.length === 0 && (
              <Welcome
                onAsk={(q) => void send(q)}
                disabled={!chat.canSend}
                onVoice={() => { speaker.unlock(); setVoiceRequest((n) => n + 1); }}
                onLive={() => voiceSession.startLive()}
                micSupported={micSupported}
              />
            )}

            <AnimatePresence initial={false}>
              {chat.turns.map((t) => {
                if (t.status === 'done') answerIndex += 1;
                const idx = answerIndex;
                return (
                  <motion.article key={t.key} layout="position" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.28 }} className="space-y-3">
                    <div className="flex justify-end">
                      <div className="max-w-[85%] rounded-2xl rounded-br-md bg-primary shadow-sm text-primary-foreground px-4 py-2.5 whitespace-pre-wrap break-words text-[.95rem]">
                        {t.question}
                      </div>
                    </div>
                    {t.status === 'pending' && (
                      <div className="paper px-5 py-4 space-y-2 text-sm" role="status">
                        <div className="flex items-center gap-3 text-muted-foreground">
                          <span className="dots flex gap-1" aria-hidden="true"><span /><span /><span /></span>
                          {t.streamingText ? 'AI đang diễn đạt từ nguồn đã truy xuất…' : 'Đang truy xuất điều khoản và soạn câu trả lời…'}
                        </div>
                        {t.streamingText && <div className="text-foreground text-[.95rem] pt-1"><RichText text={t.streamingText} /></div>}
                      </div>
                    )}
                    {t.status === 'error' && (
                      <div role="alert" className="paper border-destructive/40 px-5 py-3.5 text-sm">
                        <p className="font-medium text-destructive">Chưa nhận được câu trả lời</p>
                        <p className="text-muted-foreground mt-0.5">{t.error}</p>
                        <div className="flex gap-2 mt-2.5">
                          <button type="button" className="btn btn-outline btn-sm" disabled={!chat.canSend}
                            onClick={() => { chat.dismissTurn(t.key); void send(t.question); }} data-testid={`button-retry-${t.key}`}><RotateCw /> Gửi lại</button>
                          <button type="button" className="btn btn-ghost btn-sm" onClick={() => chat.dismissTurn(t.key)} data-testid={`button-dismiss-${t.key}`}>Bỏ qua</button>
                        </div>
                      </div>
                    )}
                    {t.status === 'done' && t.answer && (
                      <AnswerCard
                        answer={t.answer} index={idx} turnKey={t.key} onFollowUp={(q) => void send(q)} followUpDisabled={!chat.canSend}
                        speaker={speaker} speechText={answerSpeech(t.answer)}
                        onCopied={(ok) => toast(ok ? { title: 'Đã sao chép', description: 'Nội dung đã nằm trong bộ nhớ tạm.' } : { title: 'Không sao chép được', description: 'Trình duyệt chặn quyền truy cập bộ nhớ tạm.' })}
                      />
                    )}
                  </motion.article>
                );
              })}
            </AnimatePresence>
            <div ref={bottom} />
          </div>
        </div>

        <div className={cn('bottom-0 z-10 px-4 sm:px-8 pb-4 pt-2 bg-gradient-to-t from-background via-background to-background/0',
          chat.turns.length > 0 ? 'sticky' : 'relative sm:sticky')}>
          <div className="max-w-3xl mx-auto">
            {voiceSession.liveEnabled && (
              <div className="voice-bar mb-2 flex flex-wrap items-center gap-2.5 rounded-full border border-seal/40 bg-seal/8 px-3.5 py-1.5 text-xs shadow-sm" role="status" data-testid="status-live">
                <Radio className="w-3.5 h-3.5 text-seal animate-pulse shrink-0" aria-hidden="true" />
                <span className="flex-1 font-medium text-foreground">
                  {voiceSession.statusNote || LIVE_LABELS[voiceSession.livePhase]}
                </span>
                {speaker.phase !== 'idle' && (
                  <button type="button" className="btn btn-outline btn-sm !min-h-7" onClick={voiceSession.bargeIn} data-testid="button-live-barge-in">
                    <Mic /> Ngắt lời
                  </button>
                )}
                <button type="button" className="btn btn-ghost btn-sm !min-h-7" onClick={voiceSession.stopLive} data-testid="button-stop-live">
                  <Square /> Tắt Live
                </button>
              </div>
            )}
            {speaker.phase !== 'idle' && !voiceSession.liveEnabled && (
              <div className="voice-bar mb-2 flex items-center gap-3 rounded-full border border-seal/30 bg-paper px-3 py-1.5 text-xs shadow-sm" role="status" data-testid="status-playback">
                {speaker.phase === 'loading' ? <Loader2 className="w-3.5 h-3.5 animate-spin text-seal" aria-hidden="true" /> : <span className="wave" data-phase="listening" aria-hidden="true"><i /><i /><i /><i /><i /></span>}
                <span className="flex-1">
                  {speaker.phase === 'loading' ? 'Đang tạo giọng đọc…' : speaker.usingFallback ? 'Đang đọc bằng giọng trình duyệt dự phòng' : 'Đang đọc câu trả lời'}
                </span>
                <button type="button" className="btn btn-ghost btn-sm !min-h-7" onClick={speaker.stop} data-testid="button-stop-playback"><Square /> Dừng đọc</button>
              </div>
            )}
            <Composer
              key={chat.sessionId}
              onVoiceStart={() => { speaker.unlock(); speaker.stop(); }}
              onFinalSpeech={(text) => voiceSession.handleFinalTranscript(text, prefs.autoSendVoice)}
              voiceRequest={voiceRequest}
              stopVoiceRequest={stopVoiceRequest}
              liveEnabled={voiceSession.liveEnabled}
              onToggleLive={voiceSession.toggleLive}
              pendingVoiceText={voiceSession.pendingText}
              onCancelPendingVoice={voiceSession.cancelPendingSend}
              onSendPendingNow={voiceSession.sendPendingNow}
              isSpeaking={speaker.phase !== 'idle'}
              onBargeIn={voiceSession.bargeIn}
              sttFallback={sttFallback}
              llmAvailable={llmAvailable}
              value={draft} onChange={setDraft} onSubmit={() => void send(draft)} canSend={chat.canSend}
              blockedReason={blockedReason} refDate={refDate} onRefDate={setRefDate}
              useAi={effectiveUseAi} onUseAi={(v) => prefs.set('aiEnabled', v)}
            />
            <div className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1 mt-2 px-2">
              <button type="button" role="switch" aria-checked={prefs.autoSpeak} onClick={toggleAuto}
                className={cn('inline-flex items-center gap-1.5 rounded-full px-2.5 h-7 text-[.72rem] border transition-colors', prefs.autoSpeak ? 'border-seal/40 bg-seal/10 text-seal' : 'border-border text-muted-foreground hover:bg-foreground/5')}
                data-testid="button-toggle-autospeak">
                {prefs.autoSpeak ? <Volume2 className="w-3.5 h-3.5" aria-hidden="true" /> : <VolumeX className="w-3.5 h-3.5" aria-hidden="true" />}
                Tự đọc câu trả lời: {prefs.autoSpeak ? 'bật' : 'tắt'}
              </button>
              <p className="text-[.7rem] text-muted-foreground text-center">
                Mọi câu trả lời đều kèm nguồn trích dẫn. Hãy đối chiếu văn bản chính thức với Phòng Đào tạo khi cần thiết.
              </p>
            </div>
          </div>
        </div>
      </section>

      <ConfirmDialog
        open={Boolean(deleteTarget)}
        onOpenChange={(open) => { if (!open) setDeleteTarget(null); }}
        busy={chat.deleting}
        title="Xóa vĩnh viễn hội thoại này?"
        confirmLabel="Xóa vĩnh viễn"
        onConfirm={async () => {
          if (!deleteTarget) return;
          const isCurrent = deleteTarget.id === chat.sessionId;
          if (isCurrent) voiceSession.stopLive();
          const ok = await chat.deleteSession(deleteTarget.id);
          setDeleteTarget(null);
          if (ok && isCurrent) setDraft('');
        }}
      >
        <p>Toàn bộ lượt hỏi đáp đã lưu của <strong>{deleteTarget?.title || 'hội thoại này'}</strong> sẽ bị xóa khỏi máy chủ và không thể khôi phục.</p>
        <p>Các hội thoại khác không bị ảnh hưởng.</p>
      </ConfirmDialog>
    </div>
  );
}
