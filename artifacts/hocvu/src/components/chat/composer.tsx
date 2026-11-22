import { useEffect, useRef, type FormEvent, type KeyboardEvent } from 'react';
import { ArrowUp, CalendarDays, Mic, MicOff, Radio, Sparkles, Square, X } from 'lucide-react';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { useDictation } from '@/hooks/use-voice';
import { formatDate } from '@/lib/format';
import { cn } from '@/lib/utils';

interface Props {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  canSend: boolean;
  blockedReason: string | null;
  refDate: string;
  onRefDate: (v: string) => void;
  useAi: boolean;
  onUseAi: (v: boolean) => void;
  /** Whether server has an LLM API key configured (undefined while loading). */
  llmAvailable?: boolean;
  /** Whether server supports /api/stt fallback for browsers without SpeechRecognition. */
  sttFallback?: boolean;
  onVoiceStart?: () => void;
  /** Called when speech recognition produces a final transcript. */
  onFinalSpeech?: (text: string) => void;
  /** Increment to request starting dictation (e.g. welcome CTA or Live auto-relisten). */
  voiceRequest?: number;
  /** Increment to force stopping active dictation (e.g. exiting Live mode). */
  stopVoiceRequest?: number;
  /** Hands-free Live voice conversation controls. */
  liveEnabled?: boolean;
  onToggleLive?: () => void;
  pendingVoiceText?: string | null;
  onCancelPendingVoice?: () => void;
  onSendPendingNow?: () => void;
  /** Whether the assistant is currently speaking (enables barge-in via Mic). */
  isSpeaking?: boolean;
  onBargeIn?: () => void;
}

type MicPhase = 'idle' | 'starting' | 'listening' | 'stopping';
const MAX = 4000;
const PHASE_TEXT: Record<MicPhase, string> = {
  idle: '',
  starting: 'Đang mở micro…',
  listening: 'Đang nghe — nói câu hỏi của bạn',
  stopping: 'Đang chốt bản ghi…',
};

export function Composer({
  value,
  onChange,
  onSubmit,
  canSend,
  blockedReason,
  refDate,
  onRefDate,
  useAi,
  onUseAi,
  llmAvailable,
  sttFallback = false,
  onVoiceStart,
  onFinalSpeech,
  voiceRequest = 0,
  stopVoiceRequest = 0,
  liveEnabled = false,
  onToggleLive,
  pendingVoiceText,
  onCancelPendingVoice,
  onSendPendingNow,
  isSpeaking = false,
  onBargeIn,
}: Props) {
  const area = useRef<HTMLTextAreaElement>(null);
  const base = useRef('');
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  const onFinalRef = useRef(onFinalSpeech);
  onFinalRef.current = onFinalSpeech;

  const dict = useDictation((text, final) => {
    const prefix = base.current.trim();
    const combined = ((prefix ? `${prefix} ` : '') + text).slice(0, MAX);
    onChangeRef.current(combined);
    if (final && combined.trim()) {
      onFinalRef.current?.(combined.trim());
    }
  }, { sttFallback });

  const phase: MicPhase = dict.phase;
  const active = phase !== 'idle';

  // Abort dictation when sending gets blocked (restore, delete, in-flight).
  const abortRef = useRef(dict.abort);
  abortRef.current = dict.abort;
  useEffect(() => { if (!canSend) abortRef.current(); }, [canSend]);

  useEffect(() => {
    const el = area.current; if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [value]);

  useEffect(() => {
    const fn = (e: globalThis.KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (e.key === '/' && !e.ctrlKey && !e.metaKey && !e.altKey && !t.matches('input, textarea, select, [contenteditable="true"]')) {
        e.preventDefault(); area.current?.focus();
      }
    };
    document.addEventListener('keydown', fn);
    return () => document.removeEventListener('keydown', fn);
  }, []);

  const toggleMic = () => {
    if (!dict.supported) return;
    if (active) { dict.stop(); return; }
    if (isSpeaking && onBargeIn) {
      base.current = liveEnabled ? '' : value;
      onBargeIn();
      return;
    }
    if (!canSend) return;
    onCancelPendingVoice?.();
    base.current = liveEnabled ? '' : value;
    onVoiceStart?.();
    dict.start();
  };

  const toggleRef = useRef(toggleMic);
  toggleRef.current = toggleMic;
  const seenRequest = useRef(voiceRequest);
  useEffect(() => {
    if (voiceRequest === seenRequest.current) return;
    seenRequest.current = voiceRequest;
    // Do not open a mobile keyboard while the student is trying to speak.
    area.current?.scrollIntoView?.({ behavior: 'smooth', block: 'center' });
    if (phase === 'idle') toggleRef.current();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [voiceRequest]);

  const seenStopRequest = useRef(stopVoiceRequest);
  useEffect(() => {
    if (stopVoiceRequest === seenStopRequest.current) return;
    seenStopRequest.current = stopVoiceRequest;
    abortRef.current();
  }, [stopVoiceRequest]);

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    if (!canSend || !value.trim()) return;
    onCancelPendingVoice?.();
    if (active) dict.abort();
    onSubmit();
  };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); submit(); }
  };

  const aiUnavailable = llmAvailable === false;
  const micLabel = !dict.supported ? 'Trình duyệt chưa hỗ trợ nhập giọng nói'
    : active ? (dict.mode === 'server' ? 'Dừng ghi âm và nhận dạng' : 'Dừng nghe')
    : isSpeaking ? 'Ngắt lời và nói câu mới'
    : 'Bắt đầu nói câu hỏi';

  return (
    <form onSubmit={submit} className={cn('composer paper shadow-md transition-colors', (active || liveEnabled) && 'is-listening')}>
      {active && (
        <div className="flex items-center gap-3 px-4 pt-3" role="status" aria-live="polite" data-testid="status-dictation">
          <span className="wave" aria-hidden="true" data-phase={phase}><i /><i /><i /><i /><i /></span>
          <span className="text-xs font-medium text-seal flex-1">
            {dict.mode === 'server' && phase === 'listening' ? 'Đang ghi âm — bấm Dừng khi nói xong' : PHASE_TEXT[phase]}
          </span>
          <span className="kicker hidden sm:inline">
            {liveEnabled ? 'Tự gửi sau khi nói xong' : 'Bản ghi có thể sửa trước khi gửi'}
          </span>
        </div>
      )}
      {pendingVoiceText && (
        <div className="flex flex-wrap items-center gap-2 px-4 pt-3 text-xs" role="status" aria-live="polite" data-testid="status-voice-confirm">
          <span className="w-2 h-2 rounded-full bg-jade animate-pulse" aria-hidden="true" />
          <span className="flex-1 text-foreground font-medium">Sắp gửi câu hỏi giọng nói…</span>
          <button
            type="button"
            className="btn btn-ghost btn-sm !min-h-7"
            onClick={() => { onCancelPendingVoice?.(); area.current?.focus(); }}
            data-testid="button-voice-edit"
          >
            Sửa lại
          </button>
          <button
            type="button"
            className="btn btn-primary btn-sm !min-h-7"
            onClick={() => onSendPendingNow?.()}
            data-testid="button-voice-send-now"
          >
            Gửi ngay
          </button>
        </div>
      )}
      {(dict.error || blockedReason) && (
        <div className="flex items-center gap-2 px-4 pt-2.5 text-xs text-muted-foreground" role="status">
          <span className="w-1.5 h-1.5 rounded-full bg-ochre" aria-hidden="true" />
          <span className="flex-1">{dict.error || blockedReason}</span>
          {dict.error && <button type="button" onClick={dict.clearError} aria-label="Ẩn thông báo" className="p-0.5"><X className="w-3.5 h-3.5" /></button>}
        </div>
      )}
      <label htmlFor="composer" className="sr-only">Câu hỏi về quy chế (gõ hoặc nói)</label>
      <textarea
        id="composer" ref={area} rows={1} value={value} maxLength={MAX}
        onChange={(e) => { onCancelPendingVoice?.(); dict.abort(); onChange(e.target.value); }} onKeyDown={onKey}
        placeholder={active ? 'Lời bạn nói sẽ hiện ở đây…' : 'Hỏi bằng lời hoặc gõ: Điều kiện xét học bổng khuyến khích học tập?'}
        className="block w-full resize-none bg-transparent px-4 pt-3.5 pb-2 text-[.98rem] leading-relaxed outline-none placeholder:text-muted-foreground/70"
        data-testid="input-question"
      />
      <div className="flex flex-wrap items-center gap-1.5 px-2.5 pb-2.5">
        <Popover>
          <PopoverTrigger asChild>
            <button
              type="button"
              className={cn(
                'flex items-center gap-1.5 h-8 px-2.5 rounded-md text-xs border transition-colors',
                refDate ? 'border-seal/40 bg-seal/10 text-seal' : 'border-transparent text-muted-foreground hover:bg-foreground/5',
              )}
              title="Chọn ngày hiệu lực để tra cứu phiên bản văn bản theo thời điểm"
              data-testid="button-ref-date-toggle"
            >
              <CalendarDays className="w-3.5 h-3.5" aria-hidden="true" />
              <span>{refDate ? formatDate(refDate) : 'Ngày hiệu lực'}</span>
            </button>
          </PopoverTrigger>
          <PopoverContent align="start" className="w-64 p-3 space-y-2">
            <p className="text-xs font-medium text-foreground">Tra cứu theo ngày hiệu lực</p>
            <p className="text-[.72rem] text-muted-foreground">Mặc định hệ thống tra cứu quy chế hiện hành (hôm nay). Chỉ chọn ngày nếu muốn xem phiên bản tại thời điểm khác.</p>
            <div className="flex items-center gap-1.5">
              <input
                type="date"
                value={refDate}
                onChange={(e) => onRefDate(e.target.value)}
                aria-label="Ngày hiệu lực tra cứu"
                className="field !min-h-8 text-xs flex-1"
                data-testid="input-ref-date"
              />
              {refDate && (
                <button type="button" onClick={() => onRefDate('')} aria-label="Xóa ngày hiệu lực" className="btn btn-ghost btn-icon btn-sm">
                  <X className="w-3.5 h-3.5" />
                </button>
              )}
            </div>
          </PopoverContent>
        </Popover>
        {refDate && (
          <button type="button" onClick={() => onRefDate('')} aria-label="Xóa lọc ngày hiệu lực" className="inline-flex items-center p-1 rounded hover:bg-foreground/5 text-muted-foreground">
            <X className="w-3 h-3" />
          </button>
        )}

        <button
          type="button"
          onClick={() => { if (!aiUnavailable) onUseAi(!useAi); }}
          disabled={aiUnavailable}
          aria-pressed={!aiUnavailable && useAi}
          className={cn(
            'flex items-center gap-1.5 h-8 px-2.5 rounded-md text-xs border transition-colors',
            aiUnavailable
              ? 'border-transparent text-muted-foreground/60 cursor-not-allowed'
              : useAi ? 'border-seal/50 bg-seal/10 text-seal' : 'border-transparent text-muted-foreground hover:bg-foreground/5',
          )}
          title={aiUnavailable
            ? 'Máy chủ chưa cấu hình API key AI — đang dùng chế độ trích xuất trực tiếp từ quy chế'
            : 'AI chỉ diễn đạt lại nội dung từ nguồn đã truy xuất'}
          data-testid="button-toggle-ai"
        >
          <Sparkles className="w-3.5 h-3.5" aria-hidden="true" />
          {aiUnavailable ? 'AI chưa bật trên máy chủ' : `AI diễn đạt ${useAi ? 'bật' : 'tắt'}`}
        </button>

        <span className="flex-1" />
        <span className={cn('text-[.7rem] text-muted-foreground font-mono mr-1', value.length <= 3500 && 'hidden sm:inline')}
          role={value.length > 3500 ? 'status' : undefined}>{value.length > 3500 ? `${value.length}/${MAX}` : 'Enter gửi · Shift+Enter xuống dòng'}</span>

        <div className="ml-auto flex shrink-0 items-center gap-1.5">
          {onToggleLive && (
            <button
              type="button"
              onClick={onToggleLive}
              disabled={!dict.supported || (!liveEnabled && !canSend)}
              aria-pressed={liveEnabled}
              title={!dict.supported ? 'Trình duyệt chưa hỗ trợ micro hội thoại' : liveEnabled ? 'Dừng chế độ hội thoại rảnh tay' : 'Bật hội thoại rảnh tay (nói → tự gửi → tự đọc → tự nghe tiếp)'}
              className={cn(
                'btn rounded-full gap-1.5 h-10 px-3 text-xs',
                liveEnabled ? 'btn-seal pulse-ring' : 'btn-outline',
              )}
              data-testid="button-live"
            >
              <Radio className={cn('w-4 h-4', liveEnabled && 'animate-pulse')} aria-hidden="true" />
              <span className="hidden sm:inline">{liveEnabled ? 'Live đang bật' : 'Live'}</span>
            </button>
          )}
          <button
            type="button"
            onClick={toggleMic}
            disabled={!dict.supported || (!active && !canSend && !isSpeaking)}
            aria-label={micLabel}
            aria-pressed={active}
            title={!dict.supported ? 'Trình duyệt chưa hỗ trợ nhận dạng giọng nói (thử Chrome hoặc Edge)' : micLabel}
            className={cn('btn rounded-full gap-1.5', active ? 'btn-seal pulse-ring px-3' : 'btn-outline btn-icon sm:w-auto sm:px-3')}
            data-testid="button-mic"
          >
            {!dict.supported ? <MicOff /> : active ? <Square /> : <Mic />}
            <span className={cn('text-xs', !active && 'hidden sm:inline')}>{!dict.supported ? 'Không hỗ trợ' : active ? 'Dừng' : isSpeaking ? 'Ngắt lời' : 'Nói'}</span>
          </button>
          <button type="submit" disabled={!canSend || !value.trim()} aria-label="Gửi câu hỏi" className="btn btn-primary btn-icon rounded-full" data-testid="button-send">
            <ArrowUp />
          </button>
        </div>
      </div>
    </form>
  );
}
