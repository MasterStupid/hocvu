import { test as base, expect, type Route, type Page } from '@playwright/test';
import type { DocumentItem } from '../../src/lib/api';

export const TOKEN = 'synthetic-browser-only';
const ORIGIN = 'http://127.0.0.1:4179';
export const documents: DocumentItem[] = [
  { rid: 'demo', title: 'Nguồn minh họa', kind: 'demo' },
  { rid: 'r-a', id: 'a', title: 'Quy chế thử A', filename: 'a.pdf', kind: 'uploaded', document_date: '2026-01-01' },
  { rid: 'r-b', id: 'b', title: 'Quy chế thử B', filename: 'b.docx', kind: 'uploaded', document_date: '2026-02-01' },
];
export const pdf = { name: 'synthetic.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4\nsynthetic browser fixture') };
export const reply = (route: Route, body: unknown, status = 200) =>
  route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });

type Handler = (route: Route) => Promise<void>;
export class SyntheticApi {
  calls: { method: string; path: string; body: string | null }[] = [];
  unexpected: string[] = [];
  rows = structuredClone(documents);
  handlers = new Map<string, Handler>();

  handle(method: string, path: string, handler: Handler) {
    this.handlers.set(`${method} ${path}`, handler);
  }

  /** A deterministic response gate: no sleep/timing race to test in-flight state. */
  hold(method: string, path: string, body: unknown, status = 200) {
    let release!: () => void;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    this.handle(method, path, async (route) => { await gate; await reply(route, body, status); });
    return release;
  }

  count(method: string, path: string) {
    return this.calls.filter((c) => c.method === method && c.path === path).length;
  }

  async route(route: Route) {
    const req = route.request();
    const url = new URL(req.url());
    const key = `${req.method()} ${url.pathname}`;
    // This known stylesheet is optional decoration, never fetched from the network.
    if (req.method() === 'GET' && url.origin === 'https://fonts.googleapis.com' && url.pathname === '/css2') {
      await route.fulfill({ contentType: 'text/css', body: '' });
      return;
    }
    // All routes are caught at context level before navigation, including popups.
    if (url.origin !== ORIGIN) {
      this.unexpected.push(`External request: ${key}`);
      await route.abort('blockedbyclient');
      return;
    }
    if (!url.pathname.startsWith('/api/')) {
      if (req.method() === 'GET' && !['fetch', 'xhr'].includes(req.resourceType())) {
        await route.continue();
      } else {
        this.unexpected.push(`Non-static request: ${key}`);
        await route.abort('blockedbyclient');
      }
      return;
    }
    this.calls.push({ method: req.method(), path: url.pathname, body: req.postData() });
    if (key === 'GET /api/health') {
      await reply(route, { status: 'ok', documents: 3 });
      return;
    }
    if (req.headers()['x-hocvu-token'] !== TOKEN) {
      await reply(route, { detail: 'Unauthorized' }, 401);
      return;
    }
    const handler = this.handlers.get(key);
    if (handler) { await handler(route); return; }
    if (key === 'GET /api/documents') { await reply(route, this.rows); return; }
    if (key === 'GET /api/admin/storage') {
      await reply(route, { persistent: false, backend: 'synthetic-browser' });
      return;
    }
    this.unexpected.push(`Unhandled API: ${key}`);
    await route.abort('blockedbyclient');
  }
}

export async function login(page: Page) {
  await page.goto('/documents');
  await page.getByTestId('input-admin-password').fill(TOKEN);
  await page.getByTestId('input-admin-password').press('Enter');
  await expect(page.getByTestId('button-sign-out')).toBeVisible();
}

/** Real Chromium DataTransfer/File objects (not jsdom's event polyfills). */
export async function dropFiles(page: Page, names: string[]) {
  const data = await page.evaluateHandle((files) => {
    const dt = new DataTransfer();
    files.forEach((name) => dt.items.add(new File(['synthetic drop'], name, { type: 'application/pdf' })));
    return dt;
  }, names);
  const zone = page.getByTestId('button-choose-files').locator('..');
  await zone.dispatchEvent('dragenter', { dataTransfer: data });
  await zone.dispatchEvent('dragover', { dataTransfer: data });
  await zone.dispatchEvent('drop', { dataTransfer: data });
  await data.dispose();
}

export const test = base.extend<{ api: SyntheticApi }>({
  api: [async ({ context }, use) => {
    const api = new SyntheticApi();
    const errors: string[] = [];
    context.on('page', (page) => page.on('pageerror', (e) => errors.push(e.message)));
    await context.route('**/*', (route) => api.route(route));
    await use(api);
    expect(api.unexpected, 'No request may fall through to a real API or external host').toEqual([]);
    expect(errors, 'No uncaught browser exceptions').toEqual([]);
  }, { auto: true }],
});
export { expect };
