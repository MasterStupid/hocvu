export const formatSize = (bytes: number) =>
  bytes < 1024 * 1024 ? `${Math.max(1, Math.ceil(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1).replace('.', ',')} MB`;

/** Keep internal refusal codes out of student-facing answers. */
export function refusalLabel(reason?: string): string {
  const labels: Record<string, string> = {
    'Insufficient grounded context': 'Nguồn hiện có chưa đủ rõ để kết luận cho câu hỏi này.',
    'Empty question': 'Bạn chưa nhập nội dung câu hỏi.',
    'Unsafe request': 'Câu hỏi không phù hợp với phạm vi tư vấn quy chế đào tạo.',
  };
  return reason ? labels[reason] || 'Chưa thể xác minh câu trả lời từ nguồn quy chế hiện có.' : '';
}

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

export const retrievalLabel = (p?: string) => {
  const key = String(p || '').toLowerCase();
  const labels: Record<string, string> = {
    bm25: 'BM25 (từ khóa)',
    semantic: 'Ngữ nghĩa',
    hybrid: 'Kết hợp',
    'bm25+multilingual-e5': 'Kết hợp (BM25 + E5)',
    'bm25+gemini-embed': 'Kết hợp (BM25 + Gemini)',
    'bm25+openai-embed': 'Kết hợp (BM25 + OpenAI)',
  };
  return labels[key] || (key.includes('+') ? `Kết hợp (${p})` : p || 'Chưa rõ');
};

export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = filename;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Expands abbreviations so Vietnamese TTS reads them naturally without spelling out IELTS/TOEIC/GPA. */
export function speechText(text: string): string {
  const replacements: [RegExp, string][] = [
    [/https?:\/\/[^\s)]+/gi, 'đường dẫn hiển thị trên màn hình'],
    [/\[\d+\]/g, ''],
    [/\bIELTS\b/gi, 'ai eo'],
    [/\bTOEIC\b/gi, 'tô ích'],
    [/\bGPA\b/gi, 'điểm trung bình tích lũy'],
    [/\bHBKKHT\b/gi, 'học bổng khuyến khích học tập'],
    [/\bVN[ĐD]\s*\/\s*tháng\b/gi, 'đồng mỗi tháng'],
    [/\bVN[ĐD]\b/gi, 'đồng'],
    [/\bĐRL\b/gi, 'điểm rèn luyện'],
    [/\bHPU\b/gi, 'Đại học Hải Phòng'],
    [/\bĐHHP\b/gi, 'Đại học Hải Phòng'],
    [/\bCCCD\b/gi, 'căn cước công dân'],
    [/\bHEMIS\b/gi, 'hệ thống hê mít'],
    [/\bCITADT\b/gi, 'Trung tâm Ứng dụng Công nghệ thông tin và Chuyển đổi số'],
    [/\bCT\s*-\s*CTSV\b/gi, 'Công tác sinh viên'],
    [/\bQLĐT\b/gi, 'Quản lý đào tạo'],
    [/\bBGDĐT\b/gi, 'Bộ Giáo dục và Đào tạo'],
    [/\bCNTT\b/gi, 'công nghệ thông tin'],
    [/\bKTX\b/gi, 'ký túc xá'],
    [/\bBHYT\b/gi, 'bảo hiểm y tế'],
    [/\bCĐR\b/gi, 'chuẩn đầu ra'],
    [/\bQĐ\b/gi, 'quyết định'],
    [/\bSTT\b/gi, 'số thứ tự'],
    [/\bOCR\b/gi, 'nhận dạng ký tự quang học'],
    [/\bPDF\b/gi, 'tệp pi đi ép'],
    [/\bDOCX\b/gi, 'tệp Word'],
    [/\bAI\b/g, 'trí tuệ nhân tạo'],
    [/\*\*/g, ''],
  ];
  let out = String(text || '');
  for (const [p, s] of replacements) out = out.replace(p, s);
  // Only spell out short consonant-only institutional codes (e.g., BGD, CTSV),
  // never regular uppercase Vietnamese headings or English words.
  out = out.replace(/\b[BCDĐFGHJKLMNPQRSTVWXZ]{2,5}\b/g, (code) => code.split('').join('. ') + '.');
  return out.replace(/\s+/g, ' ').trim();
}

/** Splits long speech text into natural sentence chunks for faster time-to-first-audio. */
export function splitSpeechChunks(text: string, maxChars = 240): string[] {
  const clean = text.trim();
  if (!clean) return [];
  if (clean.length <= maxChars) return [clean];
  const sentences = clean.split(/(?<=[.!?;:])\s+/).filter(Boolean);
  const chunks: string[] = [];
  let buf = '';
  for (const s of sentences) {
    if (!buf) {
      buf = s;
    } else if (buf.length + 1 + s.length <= maxChars) {
      buf = `${buf} ${s}`;
    } else {
      chunks.push(buf);
      buf = s;
    }
  }
  if (buf) chunks.push(buf);
  return chunks.length ? chunks : [clean];
}
