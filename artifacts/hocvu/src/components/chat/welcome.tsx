import { useState } from 'react';
import { motion } from 'framer-motion';
import { ChevronRight } from 'lucide-react';
import { useSuggestions } from '@/hooks/use-public';
import { describeError } from '@/lib/api';
import { cn } from '@/lib/utils';

export function Welcome({ onAsk, disabled }: { onAsk: (q: string) => void; disabled: boolean }) {
  const s = useSuggestions();
  const [open, setOpen] = useState<number | null>(0);
  return (
    <motion.section initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.45 }} className="max-w-2xl mx-auto py-8 sm:py-14">
      <span className="kicker text-seal">Sổ tay quy chế · Trợ lý tra cứu</span>
      <h2 className="font-serif text-4xl sm:text-[3.3rem] leading-[1.04] font-medium mt-3">
        Hỏi về quy chế.<br /><em className="text-seal not-italic font-normal italic">Nhận lại điều khoản.</em>
      </h2>
      <p className="text-muted-foreground mt-4 max-w-xl">
        Mỗi kết luận đi kèm số hiệu nguồn bạn có thể mở ra đối chiếu. Khi văn bản không đủ rõ, HocVu nói thẳng là chưa có căn cứ.
      </p>

      <div className="mt-10">
        <p className="kicker mb-3">Chủ đề thường gặp</p>
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
