import { describe, expect, it, vi } from 'vitest';
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { click, fixtures, json, mockHttp, mountAdmin, settled, TOKEN } from './admin-harness';

describe('Document actions', () => {
  it('previews protected extracted text, retries a failed read and caches it until logout', async () => {
    let attempts = 0;
    const http = mockHttp((path) => {
      if (path === '/api/documents/a/text') {
        attempts++;
        return attempts === 1 ? json({}, 503) : json({ title: 'Nội dung A', text: 'Điều thử nghiệm tổng hợp', chunk_count: 3 });
      }
      return undefined;
    });
    const { user, login, client } = mountAdmin();
    await login();
    await click(user, 'button-preview-a');
    const dialog = await screen.findByRole('dialog');
    await user.click(await within(dialog).findByRole('button', { name: /Thử lại/ }));
    expect(await within(dialog).findByText('Điều thử nghiệm tổng hợp')).toBeInTheDocument();
    expect(within(dialog).getByText('3 đoạn truy xuất')).toBeInTheDocument();
    const reads = http.mock.calls.filter(([url]) => String(url).endsWith('/a/text'));
    expect(reads).toHaveLength(2);
    expect(new Headers(reads[1][1]!.headers).get('X-HocVu-Token')).toBe(TOKEN);
    expect(client.getQueryData(['admin', 'text', 'a'])).toBeDefined();
    await user.keyboard('{Escape}');
    await click(user, 'button-sign-out');
    expect(client.getQueriesData({ queryKey: ['admin'] })).toEqual([]);
  });

  it.each([false, true])('updates the date and closes the dialog even if refetch fails: %s', async (failReload) => {
    let updated = false;
    const http = mockHttp((path, opts) => {
      if (path.endsWith('/a/date')) { updated = true; return json({ ...fixtures[1], document_date: '2027-05-06' }); }
      if (path === '/api/documents' && updated) return failReload ? json({}, 503) : json(fixtures.map((d) => d.id === 'a' ? { ...d, document_date: '2027-05-06' } : d));
      return undefined;
    });
    const { user, login } = mountAdmin();
    await login();
    await click(user, 'button-edit-date-a');
    expect(screen.getByTestId('input-edit-date')).toHaveValue('2026-01-01');
    fireEvent.change(screen.getByTestId('input-edit-date'), { target: { value: '2027-05-06' } });
    await click(user, 'button-date-save');
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(screen.getByText(failReload ? /Thao tác đã hoàn tất nhưng/ : /Đã sửa ngày áp dụng/)).toBeInTheDocument();
    const patch = http.mock.calls.find(([url]) => String(url).endsWith('/a/date'))![1]!;
    expect(patch.method).toBe('PATCH');
    expect(JSON.parse(patch.body as string)).toEqual({ document_date: '2027-05-06' });
    await click(user, 'button-edit-date-a');
    expect(screen.getByTestId('input-edit-date')).toHaveValue(failReload ? '2026-01-01' : '2027-05-06');
  });

  it.each([0, 401, 503])('keeps the edited date and dialog on mutation failure %s', async (status) => {
    mockHttp((path) => {
      if (!path.endsWith('/a/date')) return;
      if (!status) throw new TypeError('synthetic offline');
      return json({}, status);
    });
    const { user, login } = mountAdmin();
    await login();
    await click(user, 'button-edit-date-a');
    fireEvent.change(screen.getByTestId('input-edit-date'), { target: { value: '2027-05-06' } });
    await click(user, 'button-date-save');
    expect(await within(screen.getByRole('dialog')).findByRole('alert')).not.toBeEmptyDOMElement();
    expect(screen.getByTestId('input-edit-date')).toHaveValue('2027-05-06');
    expect(screen.getByTestId('button-date-save')).toBeEnabled();
    await click(user, 'button-date-cancel');
    await click(user, 'button-edit-date-b');
    expect(screen.getByTestId('input-edit-date')).toHaveValue('2026-02-01');
  });

  it.each([1, 2])('never deletes before confirmation, allows cancellation, then deletes %s documents', async (count) => {
    let deleted = false;
    const http = mockHttp((path, opts) => {
      if (opts.method === 'DELETE' || path.endsWith('/delete-batch')) {
        deleted = true;
        return json(count === 1 ? { status: 'ok' } : { deleted: ['a', 'b'], cleanup_pending: ['b'] });
      }
      if (path === '/api/documents' && deleted) return json(fixtures.filter((d) => d.kind === 'demo' || (count === 1 && d.id === 'b')));
      return undefined;
    });
    const { user, login } = mountAdmin();
    await login();
    const openDelete = async () => {
      if (count === 1) await click(user, 'button-delete-a');
      else {
        if (!(screen.getByTestId('checkbox-select-all') as HTMLInputElement).checked) await click(user, 'checkbox-select-all');
        await click(user, 'button-delete-selected');
      }
      await screen.findByRole('alertdialog');
    };
    await openDelete();
    expect(deleted).toBe(false);
    await click(user, 'button-confirm-cancel');
    expect(deleted).toBe(false);
    await openDelete();
    await click(user, 'button-confirm-ok');
    await settled();
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    expect(screen.queryByTestId('button-delete-a')).not.toBeInTheDocument();
    expect(screen.getByTestId('button-delete-selected')).toBeDisabled();
    expect(screen.getByText('Nguồn minh họa')).toBeInTheDocument();
    const mutations = http.mock.calls.filter(([, opts]) => opts?.method === 'DELETE' || String(opts?.body).includes('"ids"'));
    expect(mutations).toHaveLength(1);
    if (count === 2) {
      expect(JSON.parse(mutations[0][1]!.body as string)).toEqual({ ids: ['a', 'b'] });
      expect(screen.getByText(/Một số tệp gốc chưa dọn được/)).toBeInTheDocument();
    } else expect(String(mutations[0][0])).toBe('/api/documents/a');
  });

  it.each([0, 401, 503])('preserves documents and selection when batch delete fails %s', async (status) => {
    mockHttp((path) => {
      if (!path.endsWith('/delete-batch')) return;
      if (!status) throw new TypeError('offline');
      return json({}, status);
    });
    const { user, login } = mountAdmin();
    await login();
    await click(user, 'checkbox-select-all');
    await click(user, 'button-delete-selected');
    await click(user, 'button-confirm-ok');
    await settled();
    expect(screen.getByTestId('checkbox-doc-a')).toBeChecked();
    expect(screen.getByTestId('checkbox-doc-b')).toBeChecked();
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    if (!status) expect(screen.getByText(/máy chủ có thể đã hoàn tất/)).toBeInTheDocument();
  });

  it('reports deletion as committed when the list cannot reload', async () => {
    let committed = false;
    mockHttp((path, opts) => {
      if (opts.method === 'DELETE') { committed = true; return json({ status: 'ok' }); }
      if (path === '/api/documents' && committed) return json({}, 503);
      return undefined;
    });
    const { user, login } = mountAdmin();
    await login();
    await click(user, 'button-delete-a');
    await click(user, 'button-confirm-ok');
    expect(await screen.findByText(/Đã xóa 1 tài liệu.*Thao tác đã hoàn tất nhưng/)).toBeInTheDocument();
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
  });

  it.each([true, false])('creates a confirmed backup and downloads bytes using a token, persistent=%s', async (persistent) => {
    const createUrl = vi.fn(() => 'blob:synthetic-backup');
    vi.stubGlobal('URL', class extends URL {
      static createObjectURL = createUrl;
      static revokeObjectURL = vi.fn();
    });
    const anchorClick = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    const http = mockHttp((path) => {
      if (path === '/api/admin/storage/backup') return json({
        filename: 'synthetic.zip', persistent_copy: persistent,
        // A compromised server field must not send our admin token off-origin.
        download_url: persistent ? '/api/admin/storage/backups/synthetic.zip' : 'https://invalid.example/steal-token',
      });
      if (path === '/api/admin/storage/backups/synthetic.zip') return new Response('synthetic archive');
      return undefined;
    });
    const { user, login } = mountAdmin();
    await login();
    await click(user, 'button-backup');
    expect(http.mock.calls.some(([url]) => url === '/api/admin/storage/backup')).toBe(false);
    await click(user, 'button-confirm-ok');
    await click(user, 'button-download-backup');
    await waitFor(() => expect(anchorClick).toHaveBeenCalledOnce());
    const download = http.mock.calls.find(([url]) => url === '/api/admin/storage/backups/synthetic.zip')!;
    expect(new Headers(download[1]!.headers).get('X-HocVu-Token')).toBe(TOKEN);
    expect(createUrl).toHaveBeenCalledWith(expect.any(Blob));
    expect((anchorClick.mock.instances[0] as HTMLAnchorElement).download).toBe('synthetic.zip');
    expect(http.mock.calls.every(([url]) => String(url).startsWith('/api/'))).toBe(true);
  });

  it.each([0, 401, 503])('retains a created backup and offers retry after download failure %s', async (status) => {
    const http = mockHttp((path) => {
      if (path === '/api/admin/storage/backup') return json({ filename: 'retry.zip', persistent_copy: true });
      if (path === '/api/admin/storage/backups/retry.zip') {
        if (!status) throw new TypeError('offline');
        return json({}, status);
      }
      return undefined;
    });
    const { user, login } = mountAdmin();
    await login();
    await click(user, 'button-backup');
    await click(user, 'button-confirm-ok');
    await click(user, 'button-download-backup');
    expect(await screen.findByText(/Không tải được bản sao lưu:/)).toBeInTheDocument();
    expect(screen.getByTestId('button-download-backup')).toBeEnabled();
    await click(user, 'button-download-backup');
    await waitFor(() => expect(http.mock.calls.filter(([url]) => url === '/api/admin/storage/backups/retry.zip')).toHaveLength(2));
    expect(http.mock.calls.filter(([url]) => url === '/api/admin/storage/backup')).toHaveLength(1);
  });
});
