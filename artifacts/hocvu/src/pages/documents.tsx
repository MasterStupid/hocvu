import { useMemo, useState } from 'react';
import { Archive, CalendarCog, Database, Download, Eye, HardDrive, Loader2, LogOut, RefreshCcw, Trash2 } from 'lucide-react';
import { PageHeader } from '@/components/app-shell';
import { SignIn } from '@/components/admin/sign-in';
import { UploadPanel, MAX_FILES, type QueueItem } from '@/components/admin/upload-panel';
import { DateDialog, PreviewDialog } from '@/components/admin/document-dialogs';
import { ConfirmDialog } from '@/components/confirm-dialog';
import { EmptyPanel, ErrorPanel, NoticeBar, SkeletonLines } from '@/components/states';
import { useAdminDocuments, useRefreshAfterCommit, useStorageStatus } from '@/hooks/use-admin';
import { ApiError, api, describeError, type BackupResult, type DocumentItem } from '@/lib/api';
import { useAdminAuth } from '@/lib/admin-auth';
import { downloadBlob, formatDate, formatDateTime, formatSize } from '@/lib/format';
import { cn } from '@/lib/utils';

type Status = { tone: 'info' | 'ok' | 'warn' | 'error'; text: string } | null;

/** A lost response is not proof of rollback: the server may have committed. */
const mutationError = (e: unknown) =>
  e instanceof ApiError && e.unconfirmed
    ? `${describeError(e)} Chưa xác nhận được kết quả; máy chủ có thể đã hoàn tất. Hãy tải lại danh sách trước khi thử lại.`
    : describeError(e);

const metaLine = (d: DocumentItem) => [d.order && `STT ${d.order}`, d.decision_number && `QĐ ${d.decision_number}`, d.article_clause, d.document_date && formatDate(d.document_date), d.ocr && 'OCR'].filter(Boolean).join(' · ');

export default function DocumentsPage() {
  const { token } = useAdminAuth();
  return token ? <Admin token={token} /> : <SignIn />;
}

function Admin({ token }: { token: string }) {
  const { signOut } = useAdminAuth();
  const docs = useAdminDocuments(token);
  const storage = useStorageStatus(token);
  const refresh = useRefreshAfterCommit();
  const [busy, setBusy] = useState<null | 'upload' | 'delete' | 'reindex' | 'backup' | 'date'>(null);
  const [status, setStatus] = useState<Status>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [confirmIds, setConfirmIds] = useState<string[] | null>(null);
  const [confirmBackup, setConfirmBackup] = useState(false);
  const [preview, setPreview] = useState<DocumentItem | null>(null);
  const [editDate, setEditDate] = useState<DocumentItem | null>(null);
  const [backup, setBackup] = useState<BackupResult | null>(null);
  const [downloading, setDownloading] = useState(false);

  const items = docs.data || [];
  const uploads = useMemo(() => items.filter((d) => d.kind === 'uploaded' && d.id), [items]);
  const liveSelection = useMemo(() => new Set([...selected].filter((id) => uploads.some((u) => u.id === id))), [selected, uploads]);
  const authLost = docs.error instanceof ApiError && docs.error.status === 401;

  const commit = async (message: string, tone: 'ok' | 'warn' = 'ok') => {
    setStatus({ tone, text: message });
    const failed = await refresh();
    if (failed) setStatus({ tone: 'warn', text: `${message} Thao tác đã hoàn tất nhưng chưa tải lại được danh sách: ${failed}` });
  };

  const upload = async (batch: QueueItem[]) => {
    if (busy || !batch.length) return false;
    setBusy('upload'); setStatus({ tone: 'info', text: `Đang xử lý cả lô ${batch.length} tệp và lập chỉ mục một lần…` });
    try {
      const res = await api.uploadBatch(token, batch.map((b) => b.file), batch.map((b) => ({
        ocr: b.ocr, order: b.order, decision_number: b.decision_number, article_clause: b.article_clause, document_date: b.document_date,
      })));
      await commit(`Đã tải lên và lập chỉ mục ${res.items?.length ?? batch.length} tài liệu.`);
      return true;
    } catch (e) {
      setStatus({ tone: 'error', text: `${mutationError(e)} Hàng đợi được giữ lại.` });
      return false;
    } finally { setBusy(null); }
  };

  const remove = async (ids: string[]) => {
    if (busy || !ids.length) return;
    setBusy('delete'); setStatus({ tone: 'info', text: `Đang xóa ${ids.length} tài liệu và cập nhật chỉ mục…` });
    try {
      let warning = ''; let count = ids.length;
      if (ids.length === 1) await api.deleteDocument(token, ids[0]);
      else {
        const r = await api.deleteBatch(token, ids);
        count = r.deleted.length;
        if (r.cleanup_pending?.length) warning = ' Một số tệp gốc chưa dọn được trên đĩa.';
      }
      setSelected((s) => { const n = new Set(s); ids.forEach((i) => n.delete(i)); return n; });
      setConfirmIds(null);
      await commit(`Đã xóa ${count} tài liệu và cập nhật chỉ mục.${warning}`, warning ? 'warn' : 'ok');
    } catch (e) {
      setConfirmIds(null);
      setStatus({ tone: 'error', text: mutationError(e) });
    } finally { setBusy(null); }
  };

  const reindex = async () => {
    if (busy) return;
    setBusy('reindex'); setStatus({ tone: 'info', text: 'Đang xây dựng lại chỉ mục tìm kiếm…' });
    try {
      const r = await api.reindex(token);
      await commit(`Đã lập chỉ mục ${r.documents} tài liệu với ${r.chunks} đoạn nội dung.`);
    } catch (e) { setStatus({ tone: 'error', text: mutationError(e) }); }
    finally { setBusy(null); }
  };

  const saveDate = async (doc: DocumentItem, date: string) => {
    setBusy('date');
    try {
      await api.updateDate(token, doc.id as string, date);
      await commit('Đã sửa ngày áp dụng và cập nhật chỉ mục tìm kiếm.');
      return { ok: true };
    } catch (e) { return { ok: false, message: mutationError(e) }; }
    finally { setBusy(null); }
  };

  const runBackup = async () => {
    if (busy) return;
    setBusy('backup'); setBackup(null); setStatus({ tone: 'info', text: 'Đang tạo và kiểm tra bản sao lưu riêng tư…' });
    try {
      const r = await api.backup(token);
      setBackup(r); setConfirmBackup(false);
      setStatus(r.persistent_copy
        ? { tone: 'ok', text: 'Đã sao lưu riêng tư trên App Storage. Có thể tải thêm một bản về máy.' }
        : { tone: 'warn', text: 'Đã tạo bản sao lưu cục bộ. Hãy tải về máy; bản này chưa được lưu bền vững trên App Storage.' });
      void storage.refetch();
    } catch (e) { setConfirmBackup(false); setStatus({ tone: 'error', text: describeError(e) }); }
    finally { setBusy(null); }
  };

  const downloadBackup = async () => {
    if (!backup) return;
    const fallback = `/api/admin/storage/backups/${encodeURIComponent(backup.filename)}`;
    const path = backup.download_url?.startsWith('/api/admin/storage/backups/') ? backup.download_url : fallback;
    setDownloading(true);
    try { downloadBlob(await api.backupBlob(token, path), backup.filename); }
    catch (e) { setStatus({ tone: 'error', text: `Không tải được bản sao lưu: ${describeError(e)}` }); }
    finally { setDownloading(false); }
  };

  const toggle = (id: string, on: boolean) => setSelected((s) => { const n = new Set(s); if (on) n.add(id); else n.delete(id); return n; });
  const allOn = uploads.length > 0 && uploads.every((u) => liveSelection.has(u.id as string));

  return (
    <div className="px-4 sm:px-8 lg:px-12 py-8 sm:py-12 max-w-6xl">
      <PageHeader kicker="Khu quản trị · Đã xác thực" title="Kho tài liệu" actions={<>
        <button type="button" className="btn btn-outline" onClick={reindex} disabled={!!busy} data-testid="button-reindex">
          {busy === 'reindex' ? <Loader2 className="animate-spin" /> : <RefreshCcw />} Lập lại chỉ mục
        </button>
        <button type="button" className="btn btn-outline" onClick={() => setConfirmBackup(true)} disabled={!!busy} data-testid="button-backup">
          {busy === 'backup' ? <Loader2 className="animate-spin" /> : <Archive />} Sao lưu
        </button>
        <button type="button" className="btn btn-ghost" onClick={signOut} disabled={!!busy} data-testid="button-sign-out"><LogOut /> Đăng xuất</button>
      </>}>
        {docs.data ? `${uploads.length} tài liệu tải lên · ${items.length} nguồn đã lập chỉ mục` : 'Đang tải danh sách tài liệu…'}
      </PageHeader>

      <div className="mt-6 space-y-3">
        <StorageIndicator state={storage} />
        {status && <NoticeBar tone={status.tone} onClose={busy ? undefined : () => setStatus(null)}
          action={backup && status.tone !== 'info' ? (
            <button type="button" className="btn btn-outline btn-sm" onClick={downloadBackup} disabled={downloading} data-testid="button-download-backup">
              {downloading ? <Loader2 className="animate-spin" /> : <Download />} Tải về máy
            </button>) : undefined}>{status.text}</NoticeBar>}
        {authLost && (
          <NoticeBar tone="error" action={<button type="button" className="btn btn-outline btn-sm" onClick={signOut} data-testid="button-reauth">Đăng nhập lại</button>}>
            Mật khẩu không còn được máy chủ chấp nhận. Dữ liệu đang hiển thị có thể đã cũ.
          </NoticeBar>
        )}
      </div>

      <div className="mt-8 grid xl:grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)] gap-8 items-start">
        <UploadPanel busy={!!busy} uploading={busy === 'upload'} onUpload={upload} onMessage={(tone, text) => setStatus({ tone, text })} />

        <section aria-labelledby="lib-title" className="min-w-0">
          <div className="flex items-center justify-between gap-3 mb-3">
            <h2 id="lib-title" className="font-serif text-2xl">Nguồn đã lập chỉ mục</h2>
            <button type="button" className="btn btn-danger-ghost btn-sm" disabled={!!busy || !liveSelection.size}
              onClick={() => { if (liveSelection.size > MAX_FILES) setStatus({ tone: 'error', text: 'Mỗi lần chỉ xóa tối đa 20 tài liệu.' }); else setConfirmIds([...liveSelection]); }}
              data-testid="button-delete-selected"><Trash2 /> Xóa {liveSelection.size || ''} đã chọn</button>
          </div>

          {docs.isLoading && <SkeletonLines rows={6} />}
          {docs.isError && !docs.data && <ErrorPanel message={describeError(docs.error)} onRetry={() => docs.refetch()} retrying={docs.isFetching} />}
          {docs.isError && docs.data && !authLost && <p className="text-xs text-destructive mb-2" role="alert">Chưa tải lại được danh sách: {describeError(docs.error)} <button type="button" className="underline" onClick={() => docs.refetch()}>Thử lại</button></p>}
          {docs.data && items.length === 0 && <EmptyPanel title="Kho đang trống" icon={<Database className="w-5 h-5" />}>Tải lên văn bản đầu tiên ở khung bên cạnh.</EmptyPanel>}

          {items.length > 0 && (
            <div className="paper overflow-hidden">
              {uploads.length > 0 && (
                <label className="flex items-center gap-2.5 px-4 py-2.5 border-b border-border text-xs text-muted-foreground bg-muted/40">
                  <input type="checkbox" className="accent-[hsl(var(--seal))] w-4 h-4" checked={allOn} disabled={!!busy}
                    onChange={(e) => setSelected(e.target.checked ? new Set(uploads.map((u) => u.id as string)) : new Set())} data-testid="checkbox-select-all" />
                  Chọn tất cả tài liệu tải lên
                </label>
              )}
              <ul className="divide-y divide-border">
                {items.map((d) => {
                  const up = d.kind === 'uploaded' && !!d.id;
                  const meta = metaLine(d);
                  return (
                    <li key={d.id || d.rid} className={cn('flex gap-3 px-4 py-3.5 transition-colors', up && liveSelection.has(d.id as string) && 'bg-seal/5')}>
                      <div className="w-4 pt-1">
                        {up && <input type="checkbox" className="accent-[hsl(var(--seal))] w-4 h-4" checked={liveSelection.has(d.id as string)} disabled={!!busy}
                          onChange={(e) => toggle(d.id as string, e.target.checked)} aria-label={`Chọn ${d.title}`} data-testid={`checkbox-doc-${d.id}`} />}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <p className="font-medium leading-snug">{d.title}</p>
                          <span className={cn('text-[.65rem] font-mono uppercase tracking-wider px-1.5 py-0.5 rounded',
                            up ? 'bg-jade/12 text-jade' : 'bg-ochre/15 text-ochre')}>
                            {up ? (d.ocr ? 'Đã OCR và chuẩn hóa' : 'Đã chuẩn hóa') : 'Dữ liệu minh họa'}
                          </span>
                          <span className="text-[.65rem] font-mono text-muted-foreground">{d.format || 'DATA'}</span>
                        </div>
                        <p className="text-xs text-muted-foreground mt-1 break-words">
                          {d.filename || d.rid}{d.size ? ` · ${formatSize(d.size)}` : ''} · {d.chunk_count || 0} đoạn truy xuất · {d.uploaded_at ? formatDateTime(d.uploaded_at) : `Hiệu lực ${formatDate(d.valid_from)}`}
                        </p>
                        {meta && <p className="text-xs text-muted-foreground mt-0.5">{meta}</p>}
                        {up && (
                          <div className="flex flex-wrap gap-1 mt-2 -ml-2">
                            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setPreview(d)} data-testid={`button-preview-${d.id}`}><Eye /> Xem nội dung</button>
                            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setEditDate(d)} disabled={!!busy} data-testid={`button-edit-date-${d.id}`}><CalendarCog /> Sửa ngày</button>
                            <button type="button" className="btn btn-danger-ghost btn-sm" onClick={() => setConfirmIds([d.id as string])} disabled={!!busy} data-testid={`button-delete-${d.id}`}><Trash2 /> Xóa</button>
                          </div>
                        )}
                      </div>
                    </li>
                  );
                })}
              </ul>
            </div>
          )}
        </section>
      </div>

      <ConfirmDialog open={!!confirmIds} onOpenChange={(v) => { if (!v) setConfirmIds(null); }} busy={busy === 'delete'}
        title={`Xóa ${confirmIds?.length || 0} tài liệu?`} confirmLabel="Xóa khỏi kho" onConfirm={() => confirmIds && remove(confirmIds)}>
        <p>Tài liệu sẽ bị gỡ khỏi cơ sở tri thức và chỉ mục tìm kiếm. Cả lô được giữ nguyên nếu cập nhật chỉ mục thất bại.</p>
      </ConfirmDialog>
      <ConfirmDialog open={confirmBackup} onOpenChange={setConfirmBackup} busy={busy === 'backup'} tone="primary"
        title="Tạo bản sao lưu riêng tư?" confirmLabel="Tạo sao lưu" onConfirm={runBackup}>
        <p>Bản sao lưu gồm tài liệu và toàn bộ lịch sử hội thoại của mọi người dùng. Chỉ lưu giữ ở nơi an toàn dành cho quản trị.</p>
      </ConfirmDialog>
      <PreviewDialog token={token} doc={preview} onClose={() => setPreview(null)} />
      <DateDialog doc={editDate} onClose={() => setEditDate(null)} onSave={saveDate} />
    </div>
  );
}

function StorageIndicator({ state }: { state: ReturnType<typeof useStorageStatus> }) {
  if (state.isLoading) return <div className="h-11 rounded-md bg-muted animate-pulse" />;
  if (state.isError && !state.data) {
    return <NoticeBar tone="warn" action={<button type="button" className="btn btn-ghost btn-sm" onClick={() => state.refetch()}>Thử lại</button>}>Chưa xác minh được nơi lưu dữ liệu ({describeError(state.error)}). Không publish trước khi kiểm tra.</NoticeBar>;
  }
  const s = state.data;
  if (!s) return null;
  return (
    <div className={cn('flex items-center gap-3 rounded-md border px-4 py-2.5 text-sm', s.persistent ? 'border-jade/40 bg-jade/8' : 'border-ochre/50 bg-ochre/10')} data-testid="status-storage">
      <HardDrive className={cn('w-4 h-4', s.persistent ? 'text-jade' : 'text-ochre')} aria-hidden="true" />
      <span className="flex-1">{s.persistent
        ? 'Lưu bền vững: App Storage và PostgreSQL. Chỉ mục cục bộ có thể tự dựng lại.'
        : 'Cảnh báo: dữ liệu đang lưu cục bộ. Phải chuyển sang lưu trữ bền vững trước khi publish.'}</span>
      {s.backend && <span className="font-mono text-xs text-muted-foreground">{String(s.backend)}</span>}
    </div>
  );
}
