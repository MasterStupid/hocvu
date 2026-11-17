// Browser-scoped conversation capability. Keys match the legacy app/ui/main.js
// exactly so existing conversations remain reachable after the migration.
export const OWNER_STORAGE_KEY = 'hv_conversation_owner';
export const SESSION_STORAGE_KEY = 'hv_session_id';
export const DELETED_STORAGE_KEY = 'hv_deleted_session';

const safeGet = (k: string) => { try { return localStorage.getItem(k); } catch { return null; } };
const safeSet = (k: string, v: string) => { try { localStorage.setItem(k, v); } catch { /* private mode */ } };

function randomHex(bytes: number): string {
  const buf = new Uint8Array(bytes);
  crypto.getRandomValues(buf);
  return Array.from(buf, (b) => b.toString(16).padStart(2, '0')).join('');
}

export function uuid(): string {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  const h = randomHex(16);
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-4${h.slice(13, 16)}-${((parseInt(h[16], 16) & 3) | 8).toString(16)}${h.slice(17, 20)}-${h.slice(20, 32)}`;
}

let ownerCache: string | null = null;
/** 64 lowercase hex characters, sent only as X-HocVu-Owner. Never the admin token. */
export function ownerKey(): string {
  if (ownerCache) return ownerCache;
  let key = safeGet(OWNER_STORAGE_KEY);
  if (!key || !/^[a-f0-9]{64}$/.test(key)) {
    key = randomHex(32);
    safeSet(OWNER_STORAGE_KEY, key);
  }
  ownerCache = key;
  return key;
}

export function storedSessionId(): string | null {
  const id = safeGet(SESSION_STORAGE_KEY);
  return id && id.length <= 128 ? id : null;
}
export function storeSessionId(id: string) { safeSet(SESSION_STORAGE_KEY, id); }

export function announceDeletion(sessionId: string) {
  safeSet(DELETED_STORAGE_KEY, JSON.stringify({ sessionId, nonce: uuid() }));
}
