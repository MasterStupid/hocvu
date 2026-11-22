import { useState } from 'react';
import { motion, useReducedMotion } from 'framer-motion';
import { AudioLines, BookMarked, ChevronRight, Keyboard, Mic, MicOff, Radio, ScanSearch, Volume2 } from 'lucide-react';
import { useSuggestions } from '@/hooks/use-public';
import { describeError } from '@/lib/api';
import { cn } from '@/lib/utils';
import { UniversityLogo } from '@/components/brand';

const FLOW = [
  { icon: Mic, title: 'Nói hoặc Live', tech: 'Speech-to-Text', body: 'Nhận dạng giọng nói tiếng Việt trực tiếp (hỗ trợ hội thoại rảnh tay Live và tự động dự phòng máy chủ).' },
  { icon: ScanSearch, title: 'Truy xuất', tech: 'Hybrid RAG', body: 'Máy chủ tìm đúng điều, khoản liên quan trong kho quy chế kèm ngày hiệu lực.' },
  { icon: BookMarked, title: 'Trả lời có dẫn nguồn', tech: 'Grounded Gen', body: 'Câu trả lời bám sát văn bản đã truy xuất, kèm trích dẫn [n] để đối chiếu trực tiếp.' },
  { icon: Volume2, title: 'Nghe tức thì', tech: 'Streaming TTS', body: 'Phát giọng đọc Việt theo luồng độ trễ thấp, có giọng trình duyệt dự phòng và hỗ trợ ngắt lời.' },
];

interface Props { onAsk: (q: string) => void; disabled: boolean; onVoice: () => void; onLive?: () => void; micSupported: boolean }

export function Welcome({ onAsk, disabled, onVoice, onLive, micSupported }: Props) {
  const s = useSuggestions();
  const reduce = useReducedMotion();
  const [open, setOpen] = useState<number | null>(0);
  const [flowOpen, setFlowOpen] = useState(false);
  const startTyping = () => {
    const input = document.getElementById('composer');
    input?.focus({ preventScroll: true });
    input?.scrollIntoView?.({ behavior: reduce ? 'auto' : 'smooth', block: 'center' });
  };
  return (
    <motion.section initial={{ opacity: 0, y: reduce ? 0 : 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.45 }} className="py-1 sm:py-8">
      <div className="mb-5 flex items-center gap-3 border-b border-border pb-5">
        <UniversityLogo size={56} />
        <div className="min-w-0">
          <p className="text-xs sm:text-sm font-bold tracking-[.07em] text-primary leading-relaxed">TRƯỜNG ĐẠI HỌC HẢI PHÒNG</p>
          <p className="mt-1 text-[.72rem] sm:text-xs text-muted-foreground">HocVu AI · Trợ lý giọng nói tư vấn quy chế đào tạo</p>
        </div>
      </div>
      <div className="voice-stage relative overflow-hidden rounded-2xl px-5 sm:px-10 py-6 sm:py-12 text-sidebar-accent-foreground">
        <div className="relative grid gap-8 sm:grid-cols-[1fr_auto] items-center">
          <div>
            <span className="kicker !text-sidebar-foreground/70">Trợ lý giọng nói · Quy chế đào tạo</span>
            <h2 className="font-serif text-4xl sm:text-[3.2rem] leading-[1.04] font-medium mt-3">
              Nói câu hỏi.<br /><em className="italic font-normal text-[hsl(var(--sidebar-primary))]">Nghe điều khoản.</em>
            </h2>
            <p className="mt-4 max-w-md text-sidebar-foreground/80 text-[.95rem] hidden sm:block">
              Hỏi như đang trò chuyện với phòng Đào tạo. Bật chế độ hội thoại trực tiếp (Live) để nói liên tục, nghe câu trả lời kèm điều khoản và hỏi nối tiếp rảnh tay. Khi văn bản chưa đủ rõ, HocVu nói thẳng là chưa có căn cứ.
            </p>
            <p className="mt-3 text-sm text-sidebar-foreground/80 sm:hidden">
              Hỏi bằng giọng nói (Live rảnh tay) hoặc nhập chữ. Nhận câu trả lời kèm điều khoản đối chiếu.
            </p>
          </div>
          <div className="flex sm:flex-col items-center gap-5 sm:gap-3 justify-self-center py-2 sm:py-0">
            <button type="button" onClick={onLive || onVoice} disabled={disabled || !micSupported}
              aria-label={micSupported ? 'Bắt đầu nói câu hỏi' : 'Trình duyệt chưa hỗ trợ nhận dạng giọng nói'}
              className="mic-orb" data-testid="button-voice-cta">
              {micSupported ? <Mic className="w-9 h-9" aria-hidden="true" /> : <MicOff className="w-9 h-9" aria-hidden="true" />}
            </button>
            <div className="sm:text-center max-w-[14rem]">
              <p className="text-sm font-medium">{micSupported ? (onLive ? 'Bấm để trò chuyện Live' : 'Bấm để nói') : 'Micro chưa hỗ trợ'}</p>
              <p className="mt-1 text-[.72rem] text-sidebar-foreground/60">
                {micSupported ? 'Nói câu hỏi, nghe phản hồi và tự mở micro cho lượt tiếp theo.' : 'Hãy thử Chrome hoặc Edge, hoặc gõ câu hỏi bên dưới.'}
              </p>
              <div className="mt-3 flex flex-wrap sm:justify-center gap-2">
                {onLive && micSupported && (
                  <button type="button" onClick={onVoice} disabled={disabled}
                    className="inline-flex min-h-9 items-center gap-1.5 rounded-lg border border-white/30 px-2.5 text-xs text-white hover:bg-white/10"
                    data-testid="button-dictate-cta">
                    <Radio className="w-3.5 h-3.5" aria-hidden="true" /> Nói từng câu
                  </button>
                )}
                <button type="button" onClick={startTyping} className="inline-flex min-h-9 items-center gap-1.5 rounded-lg border border-white/30 px-3 text-sm text-white hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
                  data-testid="button-type-cta" aria-controls="composer">
                  <Keyboard className="w-4 h-4" aria-hidden="true" /> Nhập câu hỏi
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="mt-8">
        <div className="hidden sm:flex items-center gap-2 mb-3">
          <AudioLines className="w-4 h-4 text-seal" aria-hidden="true" />
          <h3 className="kicker !text-foreground">Cách một câu hỏi được xử lý</h3>
        </div>
        <button type="button" className="sm:hidden flex w-full items-center gap-2 py-3 text-left text-sm"
          onClick={() => setFlowOpen(!flowOpen)} aria-expanded={flowOpen} aria-controls="voice-flow">
          <AudioLines className="w-4 h-4 text-seal" aria-hidden="true" />
          <span className="flex-1">Cách một câu hỏi được xử lý</span>
          <ChevronRight className={cn('w-4 h-4 transition-transform', flowOpen && 'rotate-90')} aria-hidden="true" />
        </button>
        <ol id="voice-flow" className={cn('flow gap-px rounded-xl overflow-hidden border border-border bg-border sm:grid sm:grid-cols-2 lg:grid-cols-4', flowOpen ? 'grid' : 'hidden')}>
          {FLOW.map((f, i) => (
            <li key={f.title} className="bg-paper p-4 relative">
              <div className="flex items-center gap-2">
                <span className="grid place-items-center w-8 h-8 rounded-full bg-seal/10 text-seal"><f.icon className="w-4 h-4" aria-hidden="true" /></span>
                <span className="font-mono text-[.65rem] text-muted-foreground">{String(i + 1).padStart(2, '0')} · {f.tech}</span>
              </div>
              <p className="font-serif text-lg mt-2">{f.title}</p>
              <p className="text-xs text-muted-foreground mt-1 leading-relaxed">{f.body}</p>
            </li>
          ))}
        </ol>
      </div>

      <div className="mt-10">
        <p className="kicker mb-3">Hoặc chọn câu hỏi thường gặp</p>
        {s.isLoading && <div className="grid gap-2">{[0, 1, 2].map((i) => <div key={i} className="h-14 rounded-md bg-muted animate-pulse" />)}</div>}
        {s.isError && <p className="text-sm text-muted-foreground">Chưa tải được gợi ý: {describeError(s.error)} <button type="button" className="underline" onClick={() => s.refetch()} data-testid="button-retry-suggestions">Thử lại</button></p>}
        {s.isSuccess && s.data.length === 0 && <p className="text-sm text-muted-foreground">Chưa có câu hỏi gợi ý.</p>}
        <div className="divide-y divide-border border-y border-border">
          {s.data?.map((t, i) => (
            <div key={t.topic}>
              <button type="button" onClick={() => setOpen(open === i ? null : i)} aria-expanded={open === i}
                className="w-full flex items-center gap-3 py-3.5 text-left group" data-testid={`button-topic-${i}`}>
                <span className="font-mono text-xs text-muted-foreground w-6">{String(i + 1).padStart(2, '0')}</span>
                <span className="flex-1 font-medium group-hover:text-seal transition-colors">{t.topic}</span>
                <span className="text-xs text-muted-foreground">{t.questions.length} câu hỏi</span>
                <ChevronRight className={cn('w-4 h-4 transition-transform', open === i && 'rotate-90')} aria-hidden="true" />
              </button>
              {open === i && (
                <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex flex-wrap gap-2 pb-4 pl-9">
                  {t.questions.map((q, j) => (
                    <button key={j} type="button" className="chip" disabled={disabled} onClick={() => onAsk(q)} data-testid={`button-suggestion-${i}-${j}`}>{q}</button>
                  ))}
                </motion.div>
              )}
            </div>
          ))}
        </div>
      </div>
    </motion.section>
  );
}
