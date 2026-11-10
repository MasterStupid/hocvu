import { describe, expect, it } from 'vitest';
import { fireEvent, screen, waitFor } from '@testing-library/react';
import { adminDocsKey } from '@/hooks/use-admin';
import { MAX_BATCH, MAX_FILE, MAX_FILES } from '@/components/admin/upload-panel';
import { click, fixtures, json, mockHttp, mountAdmin, settled, TOKEN } from './admin-harness';

describe('Admin authentication and upload through real React UI and transport', () => {
  it('rejects a wrong password, accepts a correct password, and clears all private caches on logout', async () => {
    const http = mockHttp();
    const { user, client, login } = mountAdmin();
    await user.type(screen.getByTestId('input-admin-password'), 'wrong-synthetic');
    await click(user, 'button-sign-in');
    expect(await screen.findByRole('alert')).toHaveTextContent('Mật khẩu không đúng');
    expect(screen.queryByTestId('button-sign-out')).not.toBeInTheDocument();
    expect(client.getQueryData(adminDocsKey)).toBeUndefined();
    await user.clear(screen.getByTestId('input-admin-password'));
    await login();
    expect(client.getQueryData(adminDocsKey)).toEqual(fixtures);
    client.setQueryData(['admin', 'text', 'a'], { text: 'private' });
    client.setQueryData(['catalog'], ['public']);
    const storageQuery = client.getQueryCache().find({ queryKey: ['admin', 'storage'] })!;
    await click(user, 'button-sign-out');
    expect(await screen.findByTestId('input-admin-password')).toHaveValue('');
    expect(client.getQueriesData({ queryKey: ['admin'] })).toEqual([]);
    expect(client.getQueryData(['catalog'])).toEqual(['public']);
    expect(storageQuery.state.fetchStatus).toBe('idle');
    expect(JSON.stringify(localStorage)).not.toContain(TOKEN);
    expect(JSON.stringify(sessionStorage)).not.toContain(TOKEN);
    const count = http.mock.calls.length;
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(http.mock.calls).toHaveLength(count);
  });

  it('uploads files in order with independent metadata, OCR defaults and overrides, then clears the queue', async () => {
    let form: FormData | undefined;
    const http = mockHttp((path, opts) => {
      if (path.endsWith('/upload-batch')) { form = opts.body as FormData; return json({ items: fixtures.slice(1) }); }
      return undefined;
    });
    const { user, login, addFiles } = mountAdmin();
    await login();
    await click(user, 'switch-default-ocr');
    addFiles([new File(['a'], 'a.pdf'), new File(['b'], 'b.docx')]);
    for (const [idx, order, decision, article, date] of [
      [0, '12', 'SYN-A', 'Điều 1', '2026-03-04'],
      [1, '7', 'SYN-B', 'Khoản 2', '2025-09-10'],
    ] as const) {
      fireEvent.change(screen.getByTestId(`input-order-${idx}`), { target: { value: order } });
      fireEvent.change(screen.getByTestId(`input-decision-${idx}`), { target: { value: decision } });
      fireEvent.change(screen.getByTestId(`input-article-${idx}`), { target: { value: article } });
      fireEvent.change(screen.getByTestId(`input-date-${idx}`), { target: { value: date } });
    }
    await click(user, 'switch-ocr-1');
    await click(user, 'button-upload');
    await waitFor(() => expect(screen.queryByTestId('button-upload')).not.toBeInTheDocument());
    expect(form!.getAll('files').map((file) => (file as File).name)).toEqual(['a.pdf', 'b.docx']);
    expect(JSON.parse(String(form!.get('metadata')))).toEqual([
      { ocr: true, order: '12', decision_number: 'SYN-A', article_clause: 'Điều 1', document_date: '2026-03-04' },
      { ocr: false, order: '7', decision_number: 'SYN-B', article_clause: 'Khoản 2', document_date: '2025-09-10' },
    ]);
    const options = http.mock.calls.find(([url]) => String(url).endsWith('/upload-batch'))![1]!;
    expect(new Headers(options.headers).get('X-HocVu-Token')).toBe(TOKEN);
    expect(new Headers(options.headers).has('Content-Type')).toBe(false); // browser owns multipart boundary
  });

  it.each([0, 401, 503])('retains files and edited metadata after upload failure %s', async (status) => {
    mockHttp((path) => {
      if (!path.endsWith('/upload-batch')) return;
      if (!status) throw new TypeError('synthetic offline');
      return json({ detail: 'Unavailable' }, status);
    });
    const { user, login, addFiles } = mountAdmin();
    await login(); addFiles();
    fireEvent.change(screen.getByTestId('input-decision-0'), { target: { value: 'KEEP-ME' } });
    await click(user, 'button-upload');
    await settled();
    expect(screen.getByTestId('input-decision-0')).toHaveValue('KEEP-ME');
    expect(screen.getByText('sample.pdf')).toBeInTheDocument();
    expect(screen.getByText(/Hàng đợi được giữ lại/)).toBeInTheDocument();
    if (!status) expect(screen.getByText(/máy chủ có thể đã hoàn tất/)).toBeInTheDocument();
    else expect(screen.queryByText(/máy chủ có thể đã hoàn tất/)).not.toBeInTheDocument();
  });

  it.each([401, 503, 0])('does not retry an already committed upload when refetch fails %s', async (status) => {
    let committed = false;
    const http = mockHttp((path) => {
      if (path.endsWith('/upload-batch')) { committed = true; return json({ items: [fixtures[1]] }); }
      if (path === '/api/documents' && committed) {
        if (!status) throw new TypeError('offline during reload');
        return json({}, status);
      }
      return undefined;
    });
    const { user, login, addFiles } = mountAdmin();
    await login(); addFiles();
    await click(user, 'button-upload');
    await screen.findByText(/Thao tác đã hoàn tất nhưng chưa tải lại được danh sách/);
    await waitFor(() => expect(screen.queryByTestId('button-upload')).not.toBeInTheDocument());
    expect(http.mock.calls.filter(([url]) => String(url).endsWith('/upload-batch'))).toHaveLength(1);
    expect(screen.queryByText(/Hàng đợi được giữ lại/)).not.toBeInTheDocument();
    if (status === 401) expect(screen.getByTestId('button-reauth')).toBeInTheDocument();
  });

  it.each([
    ['empty.pdf', 0], ['large.pdf', MAX_FILE + 1], ['bad.exe', 10],
  ])('rejects invalid file %s without sending upload', async (name, size) => {
    const http = mockHttp();
    const { login, addFiles } = mountAdmin();
    await login();
    const file = new File(['x'], name);
    Object.defineProperty(file, 'size', { value: size });
    addFiles([file]);
    expect(screen.getByText(/chỉ nhận PDF\/DOCX/)).toBeInTheDocument();
    expect(screen.queryByTestId('button-upload')).not.toBeInTheDocument();
    expect(http.mock.calls.some(([url]) => String(url).endsWith('/upload-batch'))).toBe(false);
  });

  it('accepts exactly 25 MB per file and 50 MB per batch, rejects excess total, and allows removal', async () => {
    mockHttp();
    const { user, login, addFiles } = mountAdmin();
    await login();
    const files = ['one.pdf', 'two.pdf', 'extra.pdf'].map((name, idx) => {
      const file = new File(['x'], name);
      Object.defineProperty(file, 'size', { value: idx < 2 ? MAX_FILE : 1 });
      return file;
    });
    expect(MAX_FILE * 2).toBe(MAX_BATCH);
    addFiles(files);
    expect(screen.getAllByTestId(/input-order-/)).toHaveLength(2);
    expect(screen.getByText(/Hàng đợi tối đa/)).toBeInTheDocument();
    await click(user, 'button-remove-queued-0');
    await waitFor(() => expect(screen.getAllByTestId(/input-order-/)).toHaveLength(1));
    await click(user, 'button-clear-queue');
    await waitFor(() => expect(screen.queryByTestId('button-upload')).not.toBeInTheDocument());
  });

  it('limits both file-picker and drag-drop queues to 20 files', async () => {
    mockHttp();
    const { container, user, login, addFiles } = mountAdmin();
    await login();
    addFiles(Array.from({ length: MAX_FILES }, (_, i) => new File(['x'], `${i}.pdf`)));
    const dropzone = container.querySelector('input[type=file]')!.parentElement!;
    fireEvent.drop(dropzone, { dataTransfer: { files: [new File(['x'], 'overflow.pdf')] } });
    expect(screen.getAllByTestId(/input-order-/)).toHaveLength(20);
    expect(screen.getByText(/Hàng đợi tối đa/)).toBeInTheDocument();
    await click(user, 'button-clear-queue');
    fireEvent.drop(dropzone, { dataTransfer: { files: [new File(['x'], 'dropped.pdf')] } });
    expect(await screen.findByText('dropped.pdf')).toBeInTheDocument();
  });
});
