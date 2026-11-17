import { useEffect, useRef, type FormEvent, type KeyboardEvent } from 'react';
import { ArrowUp, CalendarDays, Mic, MicOff, Sparkles, Square, X } from 'lucide-react';
import { useDictation } from '@/hooks/use-voice';
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
  onVoiceStart?: () => void;
  /** Increment to request starting dictation (e.g. welcome CTA). */
  voiceRequest?: number;
}

type MicPhase = 'idle' | 'starting' | 'listening' | 'stopping';
const MAX = 4000;
const PHASE_TEXT: Record<MicPhase, string> = {
  idle: '', starting: 'Đang mở micro…', listening: 'Đang nghe — nói câu hỏi của bạn', stopping: 'Đang chốt bản ghi…',
};

export function Composer({ value, onChange, onSubmit, canSend, blockedReason, refDate, onRefDate, useAi, onUseAi, onVoiceStart, voiceRequest = 0 }: Props) {
  const area = useRef<HTMLTextAreaElement>(null);
  const base = useRef('');
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  const dict = useDictation((text) => {
    const prefix = base.current.trim();
    onChangeRef.current(((prefix ? `${prefix} ` : '') + text).slice(0, MAX));
  });
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
    if (!canSend) return;
    base.current = value;
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

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    if (!canSend || !value.trim()) return;
    if (active) dict.abort();
    onSubmit();
  };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); submit(); }
  };

  const micLabel = !dict.supported ? 'Trình duyệt chưa hỗ trợ nhập giọng nói'
    : active ? 'Dừng nghe' : 'Bắt đầu nói câu hỏi';

  return (
    <form onSubmit={submit} className={cn('composer paper shadow-md transition-colors', active && 'is-listening')}>
      {active && (
        <div className="flex items-center gap-3 px-4 pt-3" role="status" aria-live="polite" data-testid="status-dictation">
          <span className="wave" aria-hidden="true" data-phase={phase}><i /><i /><i /><i /><i /></span>
          <span className="text-xs font-medium text-seal flex-1">{PHASE_TEXT[phase]}</span>
          <span className="kicker hidden sm:inline">Bản ghi có thể sửa trước khi gửi</span>
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
        onChange={(e) => { dict.abort(); onChange(e.target.value); }} onKeyDown={onKey}
        placeholder={active ? 'Lời bạn nói sẽ hiện ở đây…' : 'Hỏi bằng lời hoặc gõ: Điều kiện xét học bổng khuyến khích học tập?'}
        className="block w-full resize-none bg-transparent px-4 pt-3.5 pb-2 text-[.98rem] leading-relaxed outline-none placeholder:text-muted-foreground/70"
        data-testid="input-question"
      />
      <div className="flex flex-wrap items-center gap-1.5 px-2.5 pb-2.5">
        <label className="flex items-center gap-1.5 h-8 px-2 rounded-md hover:bg-foreground/5 text-xs text-muted-foreground cursor-pointer" title="Ngày hiệu lực dùng để chọn phiên bản văn bản">
          <CalendarDays className="w-3.5 h-3.5" aria-hidden="true" />
          <span className="hidden sm:inline">Hiệu lực ngày</span>
          <input type="date" value={refDate} onChange={(e) => onRefDate(e.target.value)} aria-label="Ngày hiệu lực tra cứu"
            className="bg-transparent text-foreground text-xs outline-none w-[7.4rem]" data-testid="input-ref-date" />
          {refDate && <button type="button" onClick={() => onRefDate('')} aria-label="Xóa ngày hiệu lực" className="p-0.5"><X className="w-3 h-3" /></button>}
        </label>
        <button type="button" onClick={() => onUseAi(!useAi)} aria-pressed={useAi}
          className={cn('flex items-center gap-1.5 h-8 px-2.5 rounded-md text-xs border transition-colors',
            useAi ? 'border-seal/50 bg-seal/10 text-seal' : 'border-transparent text-muted-foreground hover:bg-foreground/5')}
          title="AI chỉ diễn đạt lại nội dung từ nguồn đã truy xuất" data-testid="button-toggle-ai">
          <Sparkles className="w-3.5 h-3.5" aria-hidden="true" /> AI diễn đạt {useAi ? 'bật' : 'tắt'}
        </button>
        <span className="flex-1" />
        <span className={cn('text-[.7rem] text-muted-foreground font-mono mr-1', value.length <= 3500 && 'hidden sm:inline')}
          role={value.length > 3500 ? 'status' : undefined}>{value.length > 3500 ? `${value.length}/${MAX}` : 'Enter gửi · Shift+Enter xuống dòng'}</span>
        <div className="ml-auto flex shrink-0 items-center gap-1.5">
        <button type="button" onClick={toggleMic} disabled={!dict.supported || (!active && !canSend)}
          aria-label={micLabel} aria-pressed={active} title={!dict.supported ? 'Trình duyệt chưa hỗ trợ nhận dạng giọng nói (thử Chrome hoặc Edge)' : micLabel}
          className={cn('btn rounded-full gap-1.5', active ? 'btn-seal pulse-ring px-3' : 'btn-outline btn-icon sm:w-auto sm:px-3')} data-testid="button-mic">
          {!dict.supported ? <MicOff /> : active ? <Square /> : <Mic />}
          <span className={cn('text-xs', !active && 'hidden sm:inline')}>{!dict.supported ? 'Không hỗ trợ' : active ? 'Dừng' : 'Nói'}</span>
        </button>
        <button type="submit" disabled={!canSend || !value.trim()} aria-label="Gửi câu hỏi" className="btn btn-primary btn-icon rounded-full" data-testid="button-send">
          <ArrowUp />
        </button>
        </div>
      </div>
    </form>
  );
}
