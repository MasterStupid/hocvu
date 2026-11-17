import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, vi } from 'vitest';
import { AdminAuthProvider } from '@/lib/admin-auth';
import DocumentsPage from '@/pages/documents';
import type { DocumentItem } from '@/lib/api';

export const TOKEN = 'synthetic-test-only';
export const fixtures: DocumentItem[] = [
  { rid: 'demo', title: 'Nguồn minh họa', kind: 'demo' },
  { rid: 'r-a', id: 'a', title: 'Quy chế thử A', filename: 'a.pdf', kind: 'uploaded', document_date: '2026-01-01' },
  { rid: 'r-b', id: 'b', title: 'Quy chế thử B', filename: 'b.docx', kind: 'uploaded', document_date: '2026-02-01' },
];
export const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

type Handler = (path: string, opts: RequestInit) => Response | Promise<Response> | undefined;
export function mockHttp(handler?: Handler) {
  const calls = vi.fn(async (url: RequestInfo | URL, opts: RequestInit = {}) => {
    const path = String(url);
    const custom = await handler?.(path, opts);
    if (custom) return custom;
    if (path === '/api/documents' && (!opts.method || opts.method === 'GET')) {
      return new Headers(opts.headers).get('X-HocVu-Token') === TOKEN
        ? json(fixtures) : json({ detail: 'Unauthorized' }, 401);
    }
    if (path === '/api/admin/storage') return json({ persistent: false, backend: 'synthetic' });
    throw new Error(`Unhandled mock HTTP: ${opts.method || 'GET'} ${path}`);
  });
  vi.stubGlobal('fetch', calls);
  return calls;
}

export function mountAdmin() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity, staleTime: Infinity } },
  });
  const user = userEvent.setup();
  const view = render(
    <QueryClientProvider client={client}>
      <AdminAuthProvider><DocumentsPage /></AdminAuthProvider>
    </QueryClientProvider>,
  );
  const login = async (password = TOKEN) => {
    await user.type(screen.getByTestId('input-admin-password'), password);
    await user.click(screen.getByTestId('button-sign-in'));
    await screen.findByTestId('button-sign-out');
  };
  const addFiles = (files = [new File(['synthetic'], 'sample.pdf', { type: 'application/pdf' })]) => {
    fireEvent.change(view.container.querySelector('input[type=file]')!, { target: { files } });
  };
  return { ...view, user, client, login, addFiles };
}

export const click = async (user: ReturnType<typeof userEvent.setup>, id: string) =>
  user.click(await screen.findByTestId(id));
export const settled = async () =>
  waitFor(() => expect(screen.getByTestId('button-sign-out')).toBeEnabled());
