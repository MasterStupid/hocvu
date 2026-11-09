import { useRef, useState, type DragEvent } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { FileUp, Loader2, Upload, X } from 'lucide-react';
import { Switch } from '@/components/ui/switch';
import type { UploadMetadata } from '@/lib/api';
import { formatSize, todayISO } from '@/lib/format';
import { cn } from '@/lib/utils';

export const MAX_FILE = 25 * 1024 * 1024;
export const MAX_FILES = 20;
export const MAX_BATCH = 50 * 1024 * 1024;
const ACCEPT = '.pdf,.docx,.png,.jpg,.jpeg,.webp';

export interface QueueItem extends UploadMetadata { id: string; file: File }

export function UploadPanel({ busy, uploading, onUpload, onMessage }: {
  busy: boolean; uploading: boolean;
  onUpload: (items: QueueItem[]) => Promise<boolean>;
  onMessage: (tone: 'error', text: string) => void;
}) {
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [defaultOcr, setDefaultOcr] = useState(false);
  const [drag, setDrag] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const total = queue.reduce((s, i) => s + i.file.size, 0);

  const add = (files: File[]) => {
    const next = [...queue]; let size = total; const errors: string[] = [];
    for (const file of files) {
      if (!/\.(pdf|docx|png|jpe?g|webp)$/i.test(file.name) || !file.size || file.size > MAX_FILE) { errors.push(`${file.name}: chỉ nhận PDF/DOCX/PNG/JPG/WEBP, từ 1 byte đến 25 MB.`); continue; }
      if (next.length >= MAX_FILES || size + file.size > MAX_BATCH) { errors.push('Hàng đợi tối đa 20 tệp, tổng 50 MB. Hãy tải lô hiện tại trước khi thêm tệp.'); break; }
      size += file.size;
      next.push({ id: `${Date.now()}-${Math.random().toString(36).slice(2)}`, file, ocr: defaultOcr, order: String(next.length + 1), decision_number: '', article_clause: '', document_date: todayISO() });
    }
    setQueue(next);
    if (errors.length) onMessage('error', errors.join(' '));
    if (input.current) input.current.value = '';
  };
  const patch = (id: string, p: Partial<QueueItem>) => setQueue((q) => q.map((i) => (i.id === id ? { ...i, ...p } : i)));

  const onDrop = (e: DragEvent) => { e.preventDefault(); setDrag(false); if (!busy) add([...e.dataTransfer.files]); };
  const submit = async () => {
    const batch = queue;
    const ok = await onUpload(batch);
    if (ok) { const done = new Set(batch.map((b) => b.id)); setQueue((q) => q.filter((i) => !done.has(i.id))); }
  };

  return (
    <section className="paper overflow-hidden" aria-labelledby="upload-title">
      <header className="flex flex-wrap items-center justify-between gap-3 px-5 py-4 border-b border-border">
        <div>
          <h2 id="upload-title" className="font-serif text-2xl">Tải lên văn bản</h2>
          <p className="text-xs text-muted-foreground mt-0.5">PDF, DOCX, PNG, JPG, WEBP · tối đa 25 MB mỗi tệp, 20 tệp, tổng 50 MB mỗi lô</p>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <Switch checked={defaultOcr} onCheckedChange={setDefaultOcr} disabled={busy} data-testid="switch-default-ocr" />
          OCR mặc định cho tệp mới
        </label>
      </header>

      <div
        onDragEnter={(e) => { e.preventDefault(); if (!busy) setDrag(true); }} onDragOver={(e) => e.preventDefault()}
        onDragLeave={(e) => { e.preventDefault(); setDrag(false); }} onDrop={onDrop}
        className={cn('m-5 rounded-lg border-2 border-dashed px-6 py-8 text-center transition-colors', drag ? 'border-seal bg-seal/5' : 'border-border')}
      >
        <FileUp className={cn('w-8 h-8 mx-auto transition-transform', drag ? 'text-seal -translate-y-1' : 'text-muted-foreground')} aria-hidden="true" />
        <p className="mt-2 text-sm">Kéo thả tệp vào đây hoặc</p>
        <button type="button" className="btn btn-outline btn-sm mt-2" onClick={() => input.current?.click()} disabled={busy} data-testid="button-choose-files">Chọn tệp</button>
        <input ref={input} type="file" multiple accept={ACCEPT} className="sr-only" onChange={(e) => add([...(e.target.files || [])])} tabIndex={-1} aria-hidden="true" />
      </div>

      {queue.length > 0 && (
        <div className="px-5 pb-5">
          <div className="flex items-center justify-between mb-2">
            <p className="kicker">Hàng đợi · {queue.length}/{MAX_FILES} tệp · {formatSize(total)}</p>
            <button type="button" className="text-xs underline underline-offset-2 text-muted-foreground disabled:opacity-40" onClick={() => setQueue([])} disabled={busy} data-testid="button-clear-queue">Bỏ tất cả</button>
          </div>
          <ul className="space-y-2.5">
            <AnimatePresence initial={false}>
              {queue.map((it, idx) => (
                <motion.li key={it.id} initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }} className="rounded-md border border-border bg-background/50">
                  <div className="flex items-center gap-3 px-3.5 pt-3">
                    <span className="font-mono text-[.65rem] text-muted-foreground">{String(idx + 1).padStart(2, '0')}</span>
                    <p className="flex-1 min-w-0 truncate text-sm font-medium" title={it.file.name}>{it.file.name}</p>
                    <span className="text-xs text-muted-foreground font-mono">{formatSize(it.file.size)}</span>
                    <button type="button" className="btn btn-ghost btn-icon btn-sm" onClick={() => setQueue((q) => q.filter((x) => x.id !== it.id))} disabled={busy}
                      aria-label={`Bỏ ${it.file.name} khỏi hàng đợi`} data-testid={`button-remove-queued-${idx}`}><X /></button>
                  </div>
                  <div className="grid grid-cols-2 md:grid-cols-[5rem_1fr_1fr_9.5rem_auto] gap-2.5 px-3.5 pb-3.5 pt-2 items-end">
                    <label><span className="label">STT</span><input className="field h-9 min-h-0" type="number" min={1} maxLength={20} value={it.order} disabled={busy} onChange={(e) => patch(it.id, { order: e.target.value })} data-testid={`input-order-${idx}`} /></label>
                    <label><span className="label">Số quyết định</span><input className="field h-9 min-h-0" maxLength={100} value={it.decision_number} disabled={busy} onChange={(e) => patch(it.id, { decision_number: e.target.value })} placeholder="1234/QĐ-ĐHHP" data-testid={`input-decision-${idx}`} /></label>
                    <label><span className="label">Điều / khoản</span><input className="field h-9 min-h-0" maxLength={100} value={it.article_clause} disabled={busy} onChange={(e) => patch(it.id, { article_clause: e.target.value })} placeholder="Điều 12, Khoản 2" data-testid={`input-article-${idx}`} /></label>
                    <label><span className="label">Ngày áp dụng</span><input className="field h-9 min-h-0" type="date" value={it.document_date} disabled={busy} onChange={(e) => patch(it.id, { document_date: e.target.value })} data-testid={`input-date-${idx}`} /></label>
                    <label className="flex items-center gap-2 h-9 text-sm"><Switch checked={it.ocr} onCheckedChange={(v) => patch(it.id, { ocr: v })} disabled={busy} data-testid={`switch-ocr-${idx}`} />OCR</label>
                  </div>
                </motion.li>
              ))}
            </AnimatePresence>
          </ul>
          <button type="button" className="btn btn-seal w-full mt-4 h-11" onClick={submit} disabled={busy || !queue.length} data-testid="button-upload">
            {uploading ? <><Loader2 className="animate-spin" /> Đang xử lý và lập chỉ mục cả lô…</> : <><Upload /> Tải lên và lập chỉ mục {queue.length} tệp</>}
          </button>
        </div>
      )}
    </section>
  );
}
