import { useState } from 'react';
import { motion, useReducedMotion } from 'framer-motion';
import { AudioLines, BookMarked, ChevronRight, Mic, MicOff, ScanSearch, Volume2 } from 'lucide-react';
import { useSuggestions } from '@/hooks/use-public';
import { describeError } from '@/lib/api';
import { cn } from '@/lib/utils';
import { UniversityLogo } from '@/components/brand';

const FLOW = [
  { icon: Mic, title: 'Nói', tech: 'Speech-to-Text', body: 'Trình duyệt chuyển lời nói tiếng Việt thành văn bản. Bạn sửa bản ghi trước khi gửi.' },
  { icon: ScanSearch, title: 'Truy xuất', tech: 'Retrieval', body: 'Máy chủ tìm các điều, khoản liên quan trong kho văn bản quy chế.' },
  { icon: BookMarked, title: 'Trả lời có dẫn nguồn', tech: 'Generation', body: 'Câu trả lời chỉ dựa trên đoạn đã truy xuất, kèm số hiệu nguồn để mở ra đối chiếu.' },
  { icon: Volume2, title: 'Nghe', tech: 'Text-to-Speech', body: 'Bấm Nghe hoặc bật tự đọc để nghe câu trả lời bằng giọng Việt.' },
];

interface Props { onAsk: (q: string) => void; disabled: boolean; onVoice: () => void; micSupported: boolean }

export function Welcome({ onAsk, disabled, onVoice, micSupported }: Props) {
  const s = useSuggestions();
  const reduce = useReducedMotion();
  const [open, setOpen] = useState<number | null>(0);
  return (
    <motion.section initial={{ opacity: 0, y: reduce ? 0 : 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.45 }} className="py-1 sm:py-8">
      <div className="mb-5 flex items-center gap-3 border-b border-border pb-5">
        <UniversityLogo size={56} />
        <div className="min-w-0">
          <p className="text-xs sm:text-sm font-bold tracking-[.07em] text-primary leading-relaxed">TRƯỜNG ĐẠI HỌC HẢI PHÒNG</p>
          <p className="mt-1 text-[.72rem] sm:text-xs text-muted-foreground">HocVu AI · Trợ lý tư vấn quy chế đào tạo</p>
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
              Hỏi như đang hỏi phòng Đào tạo. HocVu tìm các điều khoản liên quan trong văn bản quy chế, trả lời kèm nguồn và đọc to cho bạn nghe. Khi văn bản không đủ rõ, HocVu nói thẳng là chưa có căn cứ.
            </p>
            <p className="mt-3 text-sm text-sidebar-foreground/80 sm:hidden">
              Hỏi bằng giọng nói hoặc nhập chữ. Nhận câu trả lời kèm điều khoản để đối chiếu.
            </p>
          </div>
          <div className="flex sm:flex-col items-center gap-5 sm:gap-3 justify-self-center py-2 sm:py-0">
            <button type="button" onClick={onVoice} disabled={disabled || !micSupported}
              aria-label={micSupported ? 'Bắt đầu nói câu hỏi' : 'Trình duyệt chưa hỗ trợ nhận dạng giọng nói'}
              className="mic-orb" data-testid="button-voice-cta">
              {micSupported ? <Mic className="w-9 h-9" aria-hidden="true" /> : <MicOff className="w-9 h-9" aria-hidden="true" />}
            </button>
            <div className="sm:text-center max-w-[13rem]">
            <p className="text-sm font-medium">{micSupported ? 'Bấm để nói' : 'Micro chưa hỗ trợ'}</p>
            <p className="mt-1 text-[.72rem] text-sidebar-foreground/60">
              {micSupported ? 'Nhận dạng chạy qua dịch vụ của trình duyệt, cần cấp quyền micro.' : 'Hãy thử Chrome hoặc Edge, hoặc gõ câu hỏi bên dưới.'}
            </p>
            </div>
          </div>
        </div>
      </div>

      <div className="mt-8">
        <div className="flex items-center gap-2 mb-3">
          <AudioLines className="w-4 h-4 text-seal" aria-hidden="true" />
          <h3 className="kicker !text-foreground">Cách một câu hỏi được xử lý</h3>
        </div>
        <ol className="flow grid gap-px rounded-xl overflow-hidden border border-border bg-border sm:grid-cols-2 lg:grid-cols-4">
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
