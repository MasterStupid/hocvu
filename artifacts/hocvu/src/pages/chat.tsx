import { useEffect, useRef, useState } from 'react';
import { useLocation, useSearch } from 'wouter';
import { AnimatePresence, motion } from 'framer-motion';
import { AlertTriangle, Download, History, Loader2, RotateCw, Square, Trash2, Volume2, VolumeX } from 'lucide-react';
import { Sheet, SheetContent, SheetDescription, SheetTitle } from '@/components/ui/sheet';
import { AnswerCard } from '@/components/chat/answer-card';
import { Composer } from '@/components/chat/composer';
import { ConversationList } from '@/components/chat/conversation-list';
import { Welcome } from '@/components/chat/welcome';
import { ConfirmDialog } from '@/components/confirm-dialog';
import { NoticeBar } from '@/components/states';
import { answerSpeech, exportTranscript, useChat, useConversations } from '@/hooks/use-chat';
import { useSpeaker } from '@/hooks/use-voice';
import { useToast } from '@/hooks/use-toast';
import { usePrefs } from '@/lib/prefs';
import { downloadBlob, todayISO } from '@/lib/format';
import { cn } from '@/lib/utils';

const DISCLAIMER = 'Kho văn bản có thể gồm dữ liệu minh họa. Hãy đối chiếu bản gốc với phòng Đào tạo trước khi quyết định.';

export default function ChatPage() {
  const chat = useChat();
  const prefs = usePrefs();
  const { toast } = useToast();
  const speaker = useSpeaker(prefs.voice, prefs.rate);
  const conversations = useConversations();
  const [draft, setDraft] = useState('');
  const [refDate, setRefDate] = useState('');
  const [listOpen, setListOpen] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);
  const search = useSearch();
  const [, navigate] = useLocation();

  // Prefill from /?q=... (used by the Library page), then clean the URL.
  useEffect(() => {
    const q = new URLSearchParams(search).get('q');
    if (q) { setDraft(q.slice(0, 4000)); navigate('/', { replace: true }); }
  }, [search, navigate]);

  useEffect(() => { bottom.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }); }, [chat.turns.length, chat.sending]);

  // The composer stays on screen, so anything scrolled into view must stop
  // above it instead of underneath (new answers, cited sources).
  const composerDock = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const dock = composerDock.current;
    const root = document.documentElement;
    if (!dock) return;
    const apply = () => { root.style.scrollPaddingBottom = `${Math.ceil(dock.getBoundingClientRect().height) + 12}px`; };
    apply();
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(apply);
    observer?.observe(dock);
    return () => { observer?.disconnect(); root.style.scrollPaddingBottom = ''; };
  }, []);

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
  const micSupported = typeof window !== 'undefined' && !!((window as unknown as Record<string, unknown>).SpeechRecognition || (window as unknown as Record<string, unknown>).webkitSpeechRecognition);
  const toggleAuto = () => {
    const next = !prefs.autoSpeak;
    if (!next) speaker.stop();
    prefs.set('autoSpeak', next);
  };

  const send = async (text: string) => {
    if (!chat.canSend || !text.trim()) return;
    speaker.stop();
    setDraft('');
    const res = await chat.ask(text, { refDate, useAi: prefs.aiEnabled });
    if (!res.ok && res.restoreText) setDraft(res.restoreText);
    if (res.ok && autoRef.current) speaker.speak(`auto-${Date.now()}`, answerSpeech(res.answer));
  };

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
  const newChat = () => { setListOpen(false); setDraft(''); chat.newChat(); };

  const list = <ConversationList currentId={chat.sessionId} onOpen={openConversation} onNew={newChat} disabled={chat.deleting} />;
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
          <button type="button" className="btn btn-danger-ghost btn-sm" onClick={() => setConfirmDelete(true)}
            disabled={chat.sending || chat.deleting || chat.restore.state === 'loading'} data-testid="button-delete-history">
            <Trash2 /> <span className="hidden sm:inline">Xóa lịch sử</span>
          </button>
        </div>

        <div className="flex-1 px-4 sm:px-8">
          <div className="max-w-3xl mx-auto py-6 space-y-6" aria-live="polite">
            {chat.notice && <NoticeBar tone={chat.notice.tone} onClose={() => chat.setNotice(null)}>{chat.notice.text}</NoticeBar>}

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

            {chat.restore.state !== 'loading' && chat.turns.length === 0 && <Welcome onAsk={send} disabled={!chat.canSend} onVoice={() => setVoiceRequest((n) => n + 1)} micSupported={micSupported} />}

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
                      <div className="paper px-5 py-4 flex items-center gap-3 text-sm text-muted-foreground" role="status">
                        <span className="dots flex gap-1" aria-hidden="true"><span /><span /><span /></span>
                        Đang truy xuất điều khoản và soạn câu trả lời…
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
                        answer={t.answer} index={idx} turnKey={t.key} onFollowUp={send} followUpDisabled={!chat.canSend}
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

        <div ref={composerDock} className={cn('bottom-0 z-10 px-4 sm:px-8 pb-2 sm:pb-4 pt-2 bg-gradient-to-t from-background via-background to-background/0',
          chat.turns.length > 0 ? 'sticky' : 'relative sm:sticky')}>
          <div className="max-w-3xl mx-auto">
            {speaker.phase !== 'idle' && (
              <div className="voice-bar mb-2 flex items-center gap-3 rounded-full border border-seal/30 bg-paper px-3 py-1.5 text-xs shadow-sm" role="status" data-testid="status-playback">
                {speaker.phase === 'loading' ? <Loader2 className="w-3.5 h-3.5 animate-spin text-seal" aria-hidden="true" /> : <span className="wave" data-phase="listening" aria-hidden="true"><i /><i /><i /><i /><i /></span>}
                <span className="flex-1">{speaker.phase === 'loading' ? 'Đang tạo giọng đọc…' : speaker.source === 'browser' ? 'Đang đọc bằng giọng của trình duyệt (giọng máy chủ tạm thời không phản hồi)' : 'Đang đọc câu trả lời'}</span>
                <button type="button" className="btn btn-ghost btn-sm !min-h-7" onClick={speaker.stop} data-testid="button-stop-playback"><Square /> Dừng đọc</button>
              </div>
            )}
            <Composer
              key={chat.sessionId} onVoiceStart={speaker.stop} voiceRequest={voiceRequest}
              value={draft} onChange={setDraft} onSubmit={() => void send(draft)} canSend={chat.canSend}
              blockedReason={blockedReason} refDate={refDate} onRefDate={setRefDate}
              useAi={prefs.aiEnabled} onUseAi={(v) => prefs.set('aiEnabled', v)}
            />
            <div className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1 mt-2 px-2">
              <button type="button" role="switch" aria-checked={prefs.autoSpeak} onClick={toggleAuto}
                className={cn('inline-flex items-center gap-1.5 rounded-full px-2.5 h-7 text-[.72rem] border transition-colors', prefs.autoSpeak ? 'border-seal/40 bg-seal/10 text-seal' : 'border-border text-muted-foreground hover:bg-foreground/5')}
                data-testid="button-toggle-autospeak">
                {prefs.autoSpeak ? <Volume2 className="w-3.5 h-3.5" aria-hidden="true" /> : <VolumeX className="w-3.5 h-3.5" aria-hidden="true" />}
                Tự đọc câu trả lời: {prefs.autoSpeak ? 'bật' : 'tắt'}
              </button>
              <p className="hidden sm:block text-[.7rem] text-muted-foreground text-center">{DISCLAIMER}</p>
            </div>
          </div>
        </div>
        {/* On phones the notice follows the transcript instead of staying on
            screen, so the fixed composer leaves more room for the answer. */}
        <p className="sm:hidden px-6 pb-4 text-[.7rem] text-muted-foreground text-center" data-testid="text-disclaimer-mobile">{DISCLAIMER}</p>
      </section>

      <ConfirmDialog
        open={confirmDelete} onOpenChange={setConfirmDelete} busy={chat.deleting}
        title="Xóa vĩnh viễn hội thoại này?" confirmLabel="Xóa vĩnh viễn"
        onConfirm={async () => { const ok = await chat.deleteCurrent(); if (ok) { setConfirmDelete(false); setDraft(''); } else setConfirmDelete(false); }}
      >
        <p>Toàn bộ lượt hỏi đáp đã lưu của hội thoại đang mở sẽ bị xóa khỏi máy chủ và không thể khôi phục.</p>
        <p>Các hội thoại khác không bị ảnh hưởng.</p>
      </ConfirmDialog>
    </div>
  );
}
