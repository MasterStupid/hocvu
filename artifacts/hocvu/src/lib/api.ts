// Typed same-origin client for the existing HocVu FastAPI backend.
const BASE = (import.meta.env.BASE_URL || '/').replace(/\/$/, '');

export function apiUrl(path: string): string {
  if (/^https?:\/\//i.test(path)) return path;
  return `${BASE}${path.startsWith('/') ? path : `/${path}`}`;
}

/* ---------- Types (mirrors app/core/models.py + app/server/app.py) ---------- */
export interface Reference {
  rid: string;
  reg_title: string;
  aid: string;
  art_heading: string;
  clause_ids: string[];
  excerpt: string;
  version?: string;
}
export interface VerdictSegment { text: string; cites?: number[] }
export interface Grounding { level: number; label: string; source_count: number }
export interface CardNote { icon?: string; text: string }
export interface AnswerCard {
  verdict_segments?: VerdictSegment[];
  grounding?: Grounding;
  notes?: CardNote[];
  suggestions?: string[];
  [key: string]: unknown;
}
export interface AskResponse {
  query: string;
  answer: string;
  references: Reference[];
  confidence: number;
  refused: boolean;
  refusal_reason: string;
  intent: string;
  audio_url: string | null;
  providers: Record<string, string>;
  timing: Record<string, number>;
  session_id: string;
  metadata: Record<string, unknown>;
  card: AnswerCard;
}
export interface AskRequest {
  question: string;
  session_id: string;
  ref_date: string | null;
  use_ai: boolean;
  with_audio: false;
}
/** One saved turn: question AND answer live in the same row. */
export interface HistoryRow {
  id?: number;
  session_id?: string;
  question: string;
  answer: string;
  intent?: string;
  refused: boolean | null;
  refusal_reason?: string;
  references: Reference[] | null;
  card: AnswerCard | null;
  article_id?: string;
  rid?: string;
  created_at?: string;
  [key: string]: unknown;
}
export interface Conversation { session_id: string; title: string; turn_count: number; updated_at: string | null }
export interface HistoryStatus { session_id: string; closed: boolean }
export interface Health {
  status: string;
  documents: number;
  voice?: string;
  retrieval?: string;
  semantic_error?: string | null;
  api_framework?: string;
  api_version?: string;
}
export interface CatalogItem { rid: string; title: string; version: string }
export interface SuggestionTopic { topic: string; questions: string[] }
export interface DocumentItem {
  rid: string;
  title: string;
  version?: string;
  valid_from?: string;
  valid_until?: string | null;
  kind: 'demo' | 'uploaded' | string;
  chunk_count?: number;
  id?: string;
  filename?: string;
  size?: number;
  format?: string;
  status?: string;
  ocr?: boolean;
  uploaded_at?: string;
  order?: string;
  decision_number?: string;
  article_clause?: string;
  document_date?: string;
}
export interface DocumentText { title: string; text: string; chunk_count?: number }
export interface UploadMetadata { ocr: boolean; order: string; decision_number: string; article_clause: string; document_date: string }
export interface UploadBatchResult { items: DocumentItem[]; [key: string]: unknown }
export interface DeleteBatchResult { deleted: string[]; cleanup_pending?: string[] }
export interface ReindexResult { documents: number; chunks: number }
export interface StorageStatus { backend?: string; persistent: boolean; document_revision?: unknown; [key: string]: unknown }
export interface BackupResult { filename: string; documents?: number; turns?: number; persistent_copy: boolean; download_url?: string; path?: string }

/* ---------- Errors ---------- */
export class ApiError extends Error {
  status: number;
  code: string;
  sessionId: string;
  retryAfter: number | null;
  constructor(message: string, status: number, code = '', sessionId = '', retryAfter: number | null = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.sessionId = sessionId;
    this.retryAfter = retryAfter;
  }
  /** status 0 = the request never got a definite answer from the server. */
  get unconfirmed() { return this.status === 0; }
}

export const isAbort = (e: unknown) => e instanceof DOMException && e.name === 'AbortError';

const str = (v: unknown) => (typeof v === 'string' && v.trim() ? v.trim() : '');
const FIELD_LABELS: Record<string, string> = {
  question: 'Câu hỏi', file: 'Tệp tải lên', files: 'Tệp tải lên', ref_date: 'Ngày tra cứu', text: 'Nội dung',
  session_id: 'Mã phiên hội thoại', document_date: 'Ngày áp dụng', ids: 'Danh sách tài liệu', metadata: 'Thông tin tệp',
};

function validationMessage(item: unknown): string {
  if (typeof item === 'string') return str(item);
  if (!item || typeof item !== 'object') return '';
  const it = item as { msg?: unknown; loc?: unknown; type?: unknown; ctx?: { max_length?: unknown } };
  const msg = str(it.msg);
  if (!msg) return '';
  const loc = Array.isArray(it.loc) ? String(it.loc[it.loc.length - 1]) : '';
  const label = FIELD_LABELS[loc] || 'Dữ liệu';
  if (it.type === 'string_too_long' && typeof it.ctx?.max_length === 'number') return `${label} không được vượt quá ${it.ctx.max_length} ký tự.`;
  if (it.type === 'missing') return `${label} là bắt buộc.`;
  if (it.type === 'json_invalid') return 'Dữ liệu gửi lên không phải JSON hợp lệ.';
  return msg;
}

const STATUS_TEXT: Record<number, string> = {
  401: 'Cần xác thực: mật khẩu hoặc khóa truy cập không hợp lệ.',
  403: 'Yêu cầu bị từ chối vì lý do bảo mật.',
  404: 'Không tìm thấy dữ liệu yêu cầu.',
  410: 'Hội thoại này đã bị đóng.',
  413: 'Dữ liệu tải lên vượt giới hạn cho phép.',
  429: 'Bạn gửi quá nhiều yêu cầu. Hãy chờ một lát rồi thử lại.',
  500: 'Máy chủ gặp lỗi khi xử lý yêu cầu.',
  502: 'Máy chủ tạm thời không phản hồi.',
  503: 'Dịch vụ lưu trữ tạm thời không khả dụng. Dữ liệu hiện có không bị thay đổi.',
};

export function errorMessage(data: unknown, status: number, fallback: string): string {
  if (data && typeof data === 'object') {
    const d = data as { error?: unknown; detail?: unknown; message?: unknown };
    // English middleware strings for 401/403/429 are replaced with Vietnamese guidance.
    const english = (s: string) => /^[\x00-\x7F]*$/.test(s);
    for (const candidate of [str(d.detail), str(d.error), str(d.message)]) {
      if (candidate && !(english(candidate) && STATUS_TEXT[status])) return candidate;
    }
    if (Array.isArray(d.detail)) {
      const msgs = [...new Set(d.detail.map(validationMessage).filter(Boolean))];
      if (msgs.length) return msgs.join(' ');
    }
  }
  return STATUS_TEXT[status] || fallback;
}

export function describeError(e: unknown, fallback = 'Đã xảy ra lỗi không xác định.'): string {
  if (e instanceof ApiError) {
    if (e.status === 429 && e.retryAfter) return `${e.message} (thử lại sau khoảng ${e.retryAfter} giây)`;
    return e.message;
  }
  if (e instanceof Error && e.message) return e.message;
  return fallback;
}

/* ---------- Transport ---------- */
interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE';
  json?: unknown;
  form?: FormData;
  owner?: string;
  token?: string | null;
  signal?: AbortSignal;
  fallback?: string;
}

async function send(path: string, opts: RequestOptions): Promise<Response> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (opts.json !== undefined) headers['Content-Type'] = 'application/json';
  if (opts.owner) headers['X-HocVu-Owner'] = opts.owner;
  if (opts.token) headers['X-HocVu-Token'] = opts.token;
  try {
    return await fetch(apiUrl(path), {
      method: opts.method || 'GET',
      headers,
      body: opts.form ?? (opts.json !== undefined ? JSON.stringify(opts.json) : undefined),
      credentials: 'same-origin',
      cache: 'no-store',
      signal: opts.signal,
    });
  } catch (e) {
    if (isAbort(e)) throw e;
    throw new ApiError('Không kết nối được máy chủ. Kiểm tra mạng rồi thử lại.', 0);
  }
}

async function failure(res: Response, fallback: string): Promise<ApiError> {
  let data: unknown = null;
  try { data = await res.json(); } catch { /* non-JSON error body */ }
  const d = (data && typeof data === 'object' ? data : {}) as { code?: unknown; session_id?: unknown };
  const ra = Number(res.headers.get('Retry-After'));
  return new ApiError(
    errorMessage(data, res.status, fallback), res.status,
    typeof d.code === 'string' ? d.code : '', typeof d.session_id === 'string' ? d.session_id : '',
    Number.isFinite(ra) && ra > 0 ? ra : null,
  );
}

export async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const fallback = opts.fallback || 'Không thể hoàn tất yêu cầu.';
  const res = await send(path, opts);
  if (!res.ok) throw await failure(res, fallback);
  try {
    return (await res.json()) as T;
  } catch {
    throw new ApiError('Máy chủ trả về dữ liệu không hợp lệ.', res.status);
  }
}

export async function requestBlob(path: string, opts: RequestOptions = {}): Promise<Blob> {
  const res = await send(path, { ...opts, json: undefined });
  if (!res.ok) throw await failure(res, 'Không tải được tệp.');
  return res.blob();
}

/* ---------- Endpoints ---------- */
const enc = encodeURIComponent;
export const api = {
  health: (signal?: AbortSignal) => request<Health>('/api/health', { signal }),
  catalog: (signal?: AbortSignal) => request<CatalogItem[]>('/api/catalog', { signal }),
  suggestions: (signal?: AbortSignal) => request<SuggestionTopic[]>('/api/suggestions', { signal }),

  ask: (owner: string, body: AskRequest, signal?: AbortSignal) =>
    request<AskResponse>('/api/ask', { method: 'POST', json: body, owner, signal, fallback: 'Không nhận được câu trả lời.' }),
  history: (owner: string, sessionId: string, signal?: AbortSignal) =>
    request<HistoryRow[]>(`/api/history?session_id=${enc(sessionId)}`, { owner, signal }),
  historyStatus: (owner: string, sessionId: string, signal?: AbortSignal) =>
    request<HistoryStatus>(`/api/history/status?session_id=${enc(sessionId)}`, { owner, signal }),
  deleteHistory: (owner: string, sessionId: string) =>
    request<{ status: string; session_id: string; deleted_turns: number }>(`/api/history?session_id=${enc(sessionId)}`, { method: 'DELETE', owner }),
  conversations: (owner: string, signal?: AbortSignal) => request<Conversation[]>('/api/conversations', { owner, signal }),
  tts: (text: string, voice: string, rate: string, signal?: AbortSignal) =>
    request<{ status: string; audio_url: string }>('/api/tts', { method: 'POST', json: { text, voice, rate }, signal, fallback: 'Không tạo được giọng đọc.' }),

  documents: (token: string, signal?: AbortSignal) => request<DocumentItem[]>('/api/documents', { token, signal }),
  documentText: (token: string, id: string, signal?: AbortSignal) => request<DocumentText>(`/api/documents/${enc(id)}/text`, { token, signal }),
  uploadBatch: (token: string, files: File[], metadata: UploadMetadata[]) => {
    const form = new FormData();
    files.forEach((f) => form.append('files', f));
    form.append('metadata', JSON.stringify(metadata));
    return request<UploadBatchResult>('/api/documents/upload-batch', { method: 'POST', form, token });
  },
  deleteDocument: (token: string, id: string) => request<{ status: string }>(`/api/documents/${enc(id)}`, { method: 'DELETE', token }),
  deleteBatch: (token: string, ids: string[]) => request<DeleteBatchResult>('/api/documents/delete-batch', { method: 'POST', json: { ids }, token }),
  updateDate: (token: string, id: string, document_date: string) =>
    request<DocumentItem>(`/api/documents/${enc(id)}/date`, { method: 'PATCH', json: { document_date }, token }),
  reindex: (token: string) => request<ReindexResult>('/api/documents/reindex', { method: 'POST', json: {}, token }),
  storage: (token: string, signal?: AbortSignal) => request<StorageStatus>('/api/admin/storage', { token, signal }),
  backup: (token: string) => request<BackupResult>('/api/admin/storage/backup', { method: 'POST', token }),
  backupBlob: (token: string, path: string) => requestBlob(path, { token }),
};
