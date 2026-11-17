import { useRef, useState } from 'react';
import { motion } from 'framer-motion';
import { BookMarked, CalendarClock, Check, ChevronDown, Copy, FileText, Loader2, Repeat2, ScanSearch, Square, Volume2 } from 'lucide-react';
import { RichText } from '@/components/chat/rich-text';
import { answerMarkdown, citeLabel, type Answer } from '@/hooks/use-chat';
import type { Grounding } from '@/lib/api';
import { cn } from '@/lib/utils';

const NOTE_ICON = { calendar: CalendarClock, document: FileText, scope: ScanSearch, replace: Repeat2 } as const;

function GroundingMeter({ g }: { g?: Grounding }) {
  const level = g?.level ?? 0;
  const strong = level >= 4; const weak = level <= 2;
  return (
    <div className="flex items-center gap-2" aria-label={`Mức căn cứ ${level} trên 5, ${g?.label || 'yếu'}, ${g?.source_count ?? 0} nguồn`}>
      <span className="flex gap-[3px] items-end h-4" aria-hidden="true">
        {[1, 2, 3, 4, 5].map((s) => (
          <motion.i key={s} initial={{ scaleY: 0 }} animate={{ scaleY: 1 }} transition={{ delay: 0.08 * s, duration: 0.3 }}
            style={{ height: `${6 + s * 2}px`, transformOrigin: 'bottom' }}
            className={cn('block w-[5px] rounded-[1px]', s <= level ? (strong ? 'bg-jade' : weak ? 'bg-ochre' : 'bg-primary') : 'bg-border')} />
        ))}
      </span>
      <span className="text-xs text-muted-foreground whitespace-nowrap">Căn cứ <b className="font-semibold text-foreground">{g?.label || 'yếu'}</b> · {g?.source_count ?? 0} nguồn</span>
    </div>
  );
}

function ModeLabel({ answer }: { answer: Answer }) {
  const llm = answer.providers?.llm;
  let text: string; let tone = '';
  if (llm === 'on') text = 'AI diễn đạt lại từ nguồn đã truy xuất';
  else if (llm === 'fallback') { text = 'AI không khả dụng · dùng câu trả lời trích xuất'; tone = 'text-ochre'; }
  else if (llm === 'off') text = 'Trả lời trích xuất · không dùng AI';
  else text = answer.restored ? 'Lượt đã lưu · không rõ chế độ diễn đạt' : 'Chế độ diễn đạt không xác định';
  return <span className={cn('ml-auto pr-2 kicker', tone)} data-testid="text-answer-mode">{text}</span>;
}

interface Props {
  answer: Answer;
  index: number;
  turnKey: string;
  onFollowUp: (q: string) => void;
  followUpDisabled: boolean;
  speaker: { activeKey: string | null; phase: 'idle' | 'loading' | 'playing'; speak: (k: string, t: string) => void; stop: () => void };
  speechText: string;
  onCopied: (ok: boolean) => void;
}

export function AnswerCard({ answer, index, turnKey, onFollowUp, followUpDisabled, speaker, speechText, onCopied }: Props) {
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const [flash, setFlash] = useState<number | null>(null);
  const [copied, setCopied] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const refs = answer.references;
  const mine = speaker.activeKey === turnKey;

  const copy = async () => {
    const text = answer.presentation === 'answer' ? answerMarkdown(answer) : answer.text;
    try { await navigator.clipboard.writeText(text); setCopied(true); onCopied(true); setTimeout(() => setCopied(false), 1600); }
    catch { onCopied(false); }
  };

  const showSource = (n: number) => {
    setSourcesOpen(true);
    setFlash(n);
    requestAnimationFrame(() => root.current?.querySelector(`[data-source="${n}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }));
    setTimeout(() => setFlash((f) => (f === n ? null : f)), 1800);
  };

  const listen = (
    <button type="button" className="btn btn-ghost btn-sm" onClick={() => (mine ? speaker.stop() : speaker.speak(turnKey, speechText))}
      aria-label={mine ? 'Dừng đọc' : 'Nghe câu trả lời'} data-testid={`button-listen-${turnKey}`}>
      {mine && speaker.phase === 'loading' ? <Loader2 className="animate-spin" /> : mine ? <Square /> : <Volume2 />}
      {mine ? (speaker.phase === 'loading' ? 'Đang tạo…' : 'Dừng') : 'Nghe'}
    </button>
  );
  const copyBtn = (
    <button type="button" className="btn btn-ghost btn-sm" onClick={copy} data-testid={`button-copy-${turnKey}`}>
      {copied ? <Check className="text-jade" /> : <Copy />}{copied ? 'Đã chép' : answer.presentation === 'answer' ? 'Chép kèm nguồn' : 'Sao chép'}
    </button>
  );

  if (answer.presentation === 'greeting' || answer.presentation === 'legacy') {
    return (
      <div className="paper px-5 py-4">
        <RichText text={answer.text} />
        {answer.presentation === 'legacy' && <p className="kicker mt-3">Lượt đã lưu · chi tiết căn cứ không có trong bản lưu này</p>}
        <div className="flex gap-1 mt-2 -ml-2">{copyBtn}{listen}</div>
      </div>
    );
  }

  if (answer.presentation === 'refusal') {
    return (
      <div className="paper border-ochre/50 px-5 py-4 bg-[repeating-linear-gradient(135deg,transparent_0_10px,hsl(var(--ochre)/.04)_10px_20px)]">
        <span className="kicker text-ochre">Không đủ căn cứ</span>
        <h3 className="font-serif text-xl mt-1">Chưa tìm thấy quy định phù hợp</h3>
        <div className="mt-2 text-[.95rem]"><RichText text={answer.text} /></div>
        {answer.refusalReason && <p className="text-xs text-muted-foreground mt-2">Lý do: {answer.refusalReason}</p>}
        <p className="text-sm text-muted-foreground mt-3">HocVu không đoán khi nguồn chưa rõ. Bạn có thể thử một câu hỏi có căn cứ:</p>
        {!!answer.card.suggestions?.length && (
          <div className="flex flex-wrap gap-2 mt-2.5">
            {answer.card.suggestions.map((q, i) => (
              <button key={i} type="button" className="chip" disabled={followUpDisabled} onClick={() => onFollowUp(q)} data-testid={`button-followup-${turnKey}-${i}`}>{q}</button>
            ))}
          </div>
        )}
        <div className="flex gap-1 mt-3 -ml-2">{copyBtn}{listen}</div>
      </div>
    );
  }

  const segments = answer.card.verdict_segments?.length ? answer.card.verdict_segments : [{ text: answer.text, cites: [] }];
  return (
    <div ref={root} className="paper overflow-hidden shadow-sm">
      <header className="flex flex-wrap items-center justify-between gap-3 px-5 py-3 border-b border-border bg-muted/40">
        <div className="flex items-baseline gap-3">
          <span className="kicker">Phiếu tra cứu · Số {String(index).padStart(2, '0')}</span>
          {answer.restored && <span className="kicker text-ochre">Đã lưu</span>}
        </div>
        <GroundingMeter g={answer.card.grounding} />
      </header>

      <div className="px-5 py-4 space-y-3 text-[.97rem] leading-[1.7]">
        <h3 className="font-serif text-lg font-medium -mb-1">Kết luận</h3>
        {segments.map((s, i) => (
          <RichText key={i} text={s.text} tail={(s.cites || []).map((c) => (
            <button key={c} type="button" className="cite" data-active={flash === c} onClick={() => showSource(c)} aria-label={`Xem nguồn ${c}`} data-testid={`button-cite-${turnKey}-${c}`}>{c}</button>
          ))} />
        ))}
      </div>

      {!!answer.card.notes?.length && (
        <section className="mx-5 mb-4 rounded-md bg-ochre/8 border border-ochre/25 px-4 py-3">
          <h4 className="kicker text-ochre mb-1.5">Lưu ý</h4>
          <ul className="space-y-1.5 text-sm">
            {answer.card.notes.map((n, i) => {
              const Icon = NOTE_ICON[(n.icon || '') as keyof typeof NOTE_ICON] || FileText;
              return <li key={i} className="flex gap-2"><Icon className="w-4 h-4 mt-0.5 text-ochre shrink-0" aria-hidden="true" /><span>{n.text}</span></li>;
            })}
          </ul>
        </section>
      )}

      {refs.length > 0 && (
        <section className="border-t border-border">
          <button type="button" onClick={() => setSourcesOpen((v) => !v)} aria-expanded={sourcesOpen}
            className="w-full flex items-center gap-2 px-5 py-3 text-sm hover:bg-muted/40 transition-colors" data-testid={`button-sources-${turnKey}`}>
            <BookMarked className="w-4 h-4 text-seal" aria-hidden="true" />
            <span className="font-medium">Nguồn tham khảo</span>
            <span className="font-mono text-xs px-1.5 rounded bg-seal/10 text-seal">{refs.length}</span>
            <ChevronDown className={cn('w-4 h-4 ml-auto transition-transform', sourcesOpen && 'rotate-180')} aria-hidden="true" />
          </button>
          {sourcesOpen && (
            <motion.ol initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} className="px-5 pb-4 grid gap-2.5">
              {refs.map((r, i) => (
                <li key={i} data-source={i + 1} tabIndex={-1}
                  className={cn('relative rounded-md border border-border bg-background/60 pl-12 pr-4 py-3', flash === i + 1 && 'source-flash')}>
                  <span className="absolute left-3 top-3 w-6 h-6 grid place-items-center rounded-sm bg-seal text-paper font-mono text-xs">{i + 1}</span>
                  <p className="text-sm font-semibold">{citeLabel(r)}</p>
                  <p className="text-xs text-muted-foreground">{r.reg_title}{r.version ? ` · Bản ${r.version}` : ''}</p>
                  {r.art_heading && <p className="text-xs mt-1 italic font-serif">{r.art_heading}</p>}
                  <blockquote className="mt-2 text-[.85rem] leading-relaxed border-l-2 border-seal/40 pl-3 text-foreground/85 whitespace-pre-line">{r.excerpt}</blockquote>
                </li>
              ))}
            </motion.ol>
          )}
        </section>
      )}

      <footer className="flex flex-wrap items-center gap-1 px-3 py-2 border-t border-border">
        {copyBtn}{listen}
        <ModeLabel answer={answer} />
      </footer>
    </div>
  );
}
