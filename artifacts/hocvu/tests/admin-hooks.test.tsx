import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { AdminAuthProvider, useAdminAuth } from '@/lib/admin-auth';
import { adminDocsKey, adminStorageKey, useAdminDocuments, useDocumentText, useRefreshAfterCommit, useStorageStatus } from '@/hooks/use-admin';
import { catalogKey, healthKey } from '@/hooks/use-public';
import { fixtures, json, mockHttp, TOKEN } from './admin-harness';

function harness() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity, staleTime: Infinity } } });
  const wrapper = ({ children }: { children: ReactNode }) =>
    <QueryClientProvider client={client}><AdminAuthProvider>{children}</AdminAuthProvider></QueryClientProvider>;
  return { client, wrapper };
}

describe('Private query lifecycle', () => {
  it('does not fetch document, storage or text data without a token or missing document ID', () => {
    const http = mockHttp();
    const { wrapper } = harness();
    renderHook(() => {
      useAdminDocuments(null);
      useStorageStatus(null);
      useDocumentText(null, 'a');
      useDocumentText(TOKEN, null);
    }, { wrapper });
    expect(http).not.toHaveBeenCalled();
  });

  it('aborts in-flight private reads on logout and prevents their late responses from restoring cache', async () => {
    let signal: AbortSignal | undefined;
    let finish!: (res: Response) => void;
    mockHttp((path, opts) => {
      if (path.endsWith('/text')) {
        signal = opts.signal as AbortSignal;
        // Deliberately ignore the abort, as a slow transport could do.
        return new Promise<Response>((resolve) => { finish = resolve; });
      }
      return undefined;
    });
    const { wrapper, client } = harness();
    const { result } = renderHook(() => {
      const auth = useAdminAuth();
      useDocumentText(auth.token, 'a');
      return auth;
    }, { wrapper });
    await act(() => result.current.signIn(TOKEN));
    await waitFor(() => expect(signal).toBeDefined());
    act(() => result.current.signOut());
    expect(signal!.aborted).toBe(true);
    expect(result.current.token).toBeNull();
    await act(async () => { finish(json({ text: 'late private text' })); });
    expect(client.getQueriesData({ queryKey: ['admin'] }).every(([, data]) => data === undefined)).toBe(true);
  });

  it('refreshes the admin list and invalidates public catalog, health and storage after a commit', async () => {
    const http = mockHttp();
    const { wrapper, client } = harness();
    client.setQueryData(adminDocsKey, []);
    client.setQueryData(catalogKey, []);
    client.setQueryData(healthKey, { documents: 0 });
    client.setQueryData(adminStorageKey, { persistent: false });
    const { result } = renderHook(() => {
      useAdminDocuments(TOKEN);
      return useRefreshAfterCommit();
    }, { wrapper });
    let error: string | null | undefined;
    await act(async () => { error = await result.current(); });
    expect(error).toBeNull();
    expect(client.getQueryData(adminDocsKey)).toEqual(fixtures);
    for (const key of [catalogKey, healthKey, adminStorageKey]) {
      expect(client.getQueryState(key)?.isInvalidated).toBe(true);
    }
    expect(http).toHaveBeenCalledOnce();
  });

  it('does not hide refetch failure or discard previously loaded documents', async () => {
    mockHttp((path) => path === '/api/documents' ? json({}, 503) : undefined);
    const { wrapper, client } = harness();
    client.setQueryData(adminDocsKey, fixtures);
    const { result } = renderHook(() => {
      useAdminDocuments(TOKEN);
      return useRefreshAfterCommit();
    }, { wrapper });
    let error: string | null | undefined;
    await act(async () => { error = await result.current(); });
    expect(error).toContain('tạm thời không khả dụng');
    expect(client.getQueryData(adminDocsKey)).toEqual(fixtures);
    expect(client.getQueryState(adminDocsKey)?.status).toBe('error');
  });
});
