export const formatSize = (bytes: number) =>
  bytes < 1024 * 1024 ? `${Math.max(1, Math.ceil(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1).replace('.', ',')} MB`;

export const todayISO = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};

export function historyGroup(value: string | null | undefined): string {
  if (!value) return 'Bản lưu cũ';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Bản lưu cũ';
  const start = new Date(); start.setHours(0, 0, 0, 0);
  const days = (start.getTime() - new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime()) / 86400000;
  return days <= 0 ? 'Hôm nay' : days <= 1 ? 'Hôm qua' : days <= 7 ? '7 ngày qua' : 'Cũ hơn';
}

export function historyTime(value: string | null | undefined): string {
  const date = value ? new Date(value) : null;
  if (!date || Number.isNaN(date.getTime())) return 'Bản lưu cũ';
  return historyGroup(value) === 'Hôm nay'
    ? date.toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' })
    : date.toLocaleDateString('vi-VN', { day: '2-digit', month: '2-digit', year: 'numeric' });
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return '';
  const d = new Date(value.length === 10 ? `${value}T00:00:00` : value);
  return Number.isNaN(d.getTime()) ? value : d.toLocaleDateString('vi-VN', { day: '2-digit', month: '2-digit', year: 'numeric' });
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '';
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value : d.toLocaleString('vi-VN', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}

export const retrievalLabel = (p?: string) =>
  ({ bm25: 'BM25 (từ khóa)', semantic: 'Ngữ nghĩa', hybrid: 'Kết hợp' } as Record<string, string>)[String(p || '').toLowerCase()] || p || 'Chưa rõ';

export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = filename;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Expands abbreviations so Vietnamese TTS reads them naturally (from legacy main.js). */
export function speechText(text: string): string {
  const replacements: [RegExp, string][] = [
    [/\bCCCD\b/gi, 'căn cước công dân'], [/\bHEMIS\b/gi, 'hệ thống hê mít'],
    [/\bCITADT\b/gi, 'Trung tâm Ứng dụng Công nghệ thông tin và Chuyển đổi số'],
    [/\bCT\s*-\s*CTSV\b/gi, 'Công tác sinh viên'], [/\bQLĐT\b/gi, 'Quản lý đào tạo'],
    [/\bĐHHP\b/gi, 'Đại học Hải Phòng'], [/\bQĐ\b/gi, 'quyết định'], [/\bSTT\b/gi, 'số thứ tự'],
    [/\bOCR\b/gi, 'nhận dạng ký tự quang học'], [/\bPDF\b/gi, 'tệp pi đi ép'], [/\bDOCX\b/gi, 'tệp Word'],
    [/\bAI\b/g, 'trí tuệ nhân tạo'], [/\*\*/g, ''],
  ];
  let out = String(text || '');
  for (const [p, s] of replacements) out = out.replace(p, s);
  return out.replace(/\b[A-ZĐ]{2,}\b/g, (code) => code.split('').join('. ') + '.');
}
