import { describe, expect, it, vi } from 'vitest';
import { api, ApiError, apiUrl, request } from '@/lib/api';
import { json, TOKEN } from './admin-harness';

describe('Admin HTTP transport', () => {
  it('encodes document identifiers and sends credentials only in the header', async () => {
    const http = vi.fn(async () => json({ text: 'synthetic' }));
    vi.stubGlobal('fetch', http);
    await api.documentText(TOKEN, 'id /?#');
    const [url, opts] = http.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('/api/documents/id%20%2F%3F%23/text');
    expect(url).not.toContain(TOKEN);
    expect(new Headers(opts.headers).get('X-HocVu-Token')).toBe(TOKEN);
    expect(opts.credentials).toBe('same-origin');
    expect(opts.cache).toBe('no-store');
    expect(apiUrl('/api/documents')).toBe('/api/documents');
  });

  it.each([401, 503, 413])('translates English and non-JSON HTTP %s errors', async (status) => {
    vi.stubGlobal('fetch', vi.fn(async () => json({ detail: 'English middleware error' }, status)));
    await expect(api.documents(TOKEN)).rejects.toMatchObject({ status });
    try { await api.documents(TOKEN); } catch (error) {
      expect((error as Error).message).not.toContain('English');
    }
    vi.stubGlobal('fetch', vi.fn(async () => new Response('<html>error</html>', { status })));
    await expect(api.documents(TOKEN)).rejects.toBeInstanceOf(ApiError);
  });

  it('distinguishes network failures, aborts and malformed successful JSON', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('offline'); }));
    await expect(api.documents(TOKEN)).rejects.toMatchObject({ status: 0, unconfirmed: true });
    const abort = new DOMException('cancelled', 'AbortError');
    vi.stubGlobal('fetch', vi.fn(async () => { throw abort; }));
    await expect(request('/api/documents', { signal: new AbortController().signal })).rejects.toBe(abort);
    vi.stubGlobal('fetch', vi.fn(async () => new Response('not JSON')));
    await expect(api.documents(TOKEN)).rejects.toMatchObject({ status: 200 });
  });

  it('surfaces backup download failure rather than saving an error body', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json({}, 401)));
    await expect(api.backupBlob(TOKEN, '/api/admin/storage/backups/synthetic.zip')).rejects.toMatchObject({ status: 401 });
  });
});
