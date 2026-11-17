import { useEffect, useRef, type FormEvent, type KeyboardEvent } from 'react';
import { ArrowUp, CalendarDays, Mic, MicOff, Sparkles, X } from 'lucide-react';
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
}

export function Composer({ value, onChange, onSubmit, canSend, blockedReason, refDate, onRefDate, useAi, onUseAi }: Props) {
  const area = useRef<HTMLTextAreaElement>(null);
  const dict = useDictation((text) => onChange(text));

  useEffect(() => {
    const el = area.current; if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [value]);

  // "/" focuses the composer from anywhere (legacy shortcut).
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

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    if (!canSend || !value.trim()) return;
    if (dict.listening) dict.abort();
    onSubmit();
  };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); submit(); }
  };

  return (
    <form onSubmit={submit} className="paper shadow-md focus-within:border-seal/60 transition-colors">
      {(dict.error || blockedReason) && (
        <div className="flex items-center gap-2 px-4 pt-2.5 text-xs text-muted-foreground" role="status">
          <span className="w-1.5 h-1.5 rounded-full bg-ochre" aria-hidden="true" />
          <span className="flex-1">{dict.error || blockedReason}</span>
          {dict.error && <button type="button" onClick={dict.clearError} aria-label="Ẩn thông báo" className="p-0.5"><X className="w-3.5 h-3.5" /></button>}
        </div>
      )}
      <label htmlFor="composer" className="sr-only">Câu hỏi về quy chế</label>
      <textarea
        id="composer" ref={area} rows={1} value={value} maxLength={4000}
        onChange={(e) => onChange(e.target.value)} onKeyDown={onKey}
        placeholder={dict.listening ? 'Đang nghe… hãy nói câu hỏi của bạn' : 'Ví dụ: Điều kiện để được xét học bổng khuyến khích học tập?'}
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
        <span className="hidden sm:inline text-[.7rem] text-muted-foreground font-mono mr-1">{value.length > 3500 ? `${value.length}/4000` : 'Enter gửi · Shift+Enter xuống dòng'}</span>
        <button type="button" onClick={dict.supported ? dict.start : undefined} disabled={!dict.supported}
          aria-label={!dict.supported ? 'Trình duyệt chưa hỗ trợ nhập giọng nói' : dict.listening ? 'Dừng ghi âm' : 'Nhập bằng giọng nói'}
          title={!dict.supported ? 'Trình duyệt chưa hỗ trợ nhận dạng giọng nói (thử Chrome hoặc Edge)' : undefined}
          className={cn('btn btn-icon rounded-full', dict.listening ? 'btn-seal pulse-ring' : 'btn-ghost')} data-testid="button-mic">
          {dict.supported ? <Mic /> : <MicOff />}
        </button>
        <button type="submit" disabled={!canSend || !value.trim()} aria-label="Gửi câu hỏi" className="btn btn-primary btn-icon rounded-full" data-testid="button-send">
          <ArrowUp />
        </button>
      </div>
    </form>
  );
}
