import { useEffect, useState, type FormEvent } from 'react';
import { Loader2 } from 'lucide-react';
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog';
import { ErrorPanel, SkeletonLines } from '@/components/states';
import { useDocumentText } from '@/hooks/use-admin';
import { useDialogReturnFocus } from '@/hooks/use-dialog-return-focus';
import { describeError, type DocumentItem } from '@/lib/api';

export function PreviewDialog({ token, doc, onClose }: { token: string; doc: DocumentItem | null; onClose: () => void }) {
  const q = useDocumentText(token, doc?.id ?? null);
  const focus = useDialogReturnFocus();
  return (
    <Dialog open={!!doc} onOpenChange={(v) => { if (!v) onClose(); }}>
      <DialogContent className="bg-paper max-w-3xl max-h-[88dvh] flex flex-col" {...focus}>
        <span className="kicker text-seal">Văn bản đã trích xuất</span>
        <DialogTitle className="font-serif text-2xl font-medium leading-tight pr-6">{q.data?.title || doc?.title}</DialogTitle>
        <DialogDescription className="text-xs">{q.data ? `${q.data.chunk_count || 0} đoạn truy xuất` : 'Đang tải nội dung…'}</DialogDescription>
        <div className="flex-1 min-h-0 overflow-y-auto scroll-thin rounded-md border border-border bg-background/60 p-4">
          {q.isLoading && <SkeletonLines rows={6} />}
          {q.isError && <ErrorPanel message={describeError(q.error)} onRetry={() => q.refetch()} retrying={q.isFetching} />}
          {q.data && <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed">{q.data.text || 'Không có văn bản trích xuất.'}</pre>}
        </div>
      </DialogContent>
    </Dialog>
  );
}

export function DateDialog({ doc, onClose, onSave }: {
  doc: DocumentItem | null; onClose: () => void;
  onSave: (doc: DocumentItem, date: string) => Promise<{ ok: boolean; message?: string }>;
}) {
  const [value, setValue] = useState('');
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<{ error: boolean; text: string } | null>(null);
  const focus = useDialogReturnFocus();
  useEffect(() => { if (doc) { setValue(doc.document_date || ''); setMsg(null); } }, [doc]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!doc || saving) return;
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) { setMsg({ error: true, text: 'Hãy chọn ngày áp dụng hợp lệ.' }); return; }
    setSaving(true); setMsg({ error: false, text: 'Đang lưu ngày và cập nhật chỉ mục…' });
    const res = await onSave(doc, value);
    setSaving(false);
    if (res.ok) onClose(); else setMsg({ error: true, text: res.message || 'Không thể lưu ngày áp dụng.' });
  };

  return (
    <Dialog open={!!doc} onOpenChange={(v) => { if (!v && !saving) onClose(); }}>
      <DialogContent className="bg-paper max-w-md" {...focus}>
        <form onSubmit={submit}>
          <span className="kicker text-seal">Sửa ngày áp dụng</span>
          <DialogTitle className="font-serif text-2xl font-medium leading-tight mt-1">{doc?.title}</DialogTitle>
          <DialogDescription className="text-sm mt-1">Chỉ thay đổi ngày áp dụng; mã tài liệu và tệp gốc được giữ nguyên.</DialogDescription>
          <label className="block mt-5"><span className="label">Ngày áp dụng</span>
            <input type="date" required className="field" value={value} onChange={(e) => setValue(e.target.value)} disabled={saving} data-testid="input-edit-date" />
          </label>
          {msg && <p role={msg.error ? 'alert' : 'status'} className={msg.error ? 'text-sm text-destructive mt-2' : 'text-sm text-muted-foreground mt-2'}>{msg.text}</p>}
          <div className="flex justify-end gap-2 mt-5">
            <button type="button" className="btn btn-ghost" onClick={onClose} disabled={saving} data-testid="button-date-cancel">Hủy</button>
            <button type="submit" className="btn btn-primary" disabled={saving} data-testid="button-date-save">{saving ? <><Loader2 className="animate-spin" /> Đang lưu</> : 'Lưu ngày'}</button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
