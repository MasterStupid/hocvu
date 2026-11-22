# HocVu AI — Trợ lý Ảo Hội thoại Tư vấn Quy chế Đào tạo (RAG + STT/TTS)

**HocVu AI** là trợ lý ảo hội thoại bằng giọng nói tiếng Việt tư vấn quy chế đào tạo cho sinh viên (**Trường Đại học Hải Phòng**), ứng dụng kiến trúc **RAG có kiểm chứng (anti-hallucination)** kết hợp **Speech-to-Text (STT)** và **Text-to-Speech (TTS)**.

## Điểm nổi bật

- **Hội thoại giọng nói rảnh tay (Live Mode):** Nói câu hỏi → đếm ngược ngắn 1,2 giây (có thể bấm sửa nhanh) → tự gửi → đọc phản hồi theo luồng → lọc vọng loa (anti-echo) → tự mở micro cho lượt tiếp theo; hỗ trợ **ngắt lời (barge-in)**.
- **STT & TTS linh hoạt, độ trễ thấp:**
  - STT ưu tiên Web Speech API (`vi-VN`), kèm lớp chuẩn hóa lỗi phiên âm thuật ngữ học vụ (`tính chỉ` → `tín chỉ`, `ai eo` → `IELTS`, `tô ích` → `TOEIC`, …) và **fallback phía máy chủ** (`POST /api/stt`) cho Safari/Firefox/WebView khi có Gemini hoặc OpenAI API key.
  - TTS phát luồng trực tiếp (`POST /api/tts/stream`) qua Microsoft Edge-TTS theo từng câu, tự động mở khóa autoplay trên di động, có **fallback giọng Việt trình duyệt (`speechSynthesis`)**, xử lý phát âm từ viết tắt tự nhiên và tự động dọn cache `.mp3` theo LRU/TTL.
- **RAG có căn cứ & chống bịa đặt:**
  - Truy xuất BM25 kết hợp từ điển đồng nghĩa văn nói sinh viên (*rớt môn*, *đuổi học*, *ra trường*, *đóng tiền học muộn*, …) và **tùy chọn tìm kiếm ngữ nghĩa (Hybrid Semantic)** bằng `intfloat/multilingual-e5-small` cục bộ hoặc **Cloud Embedding API** (Gemini/OpenAI, không cần PyTorch).
  - Hội thoại nhiều lượt (multi-turn) bảo vệ chặt chủ đề gốc, tách biệt ý định xã giao (`Cảm ơn` / `Tạm biệt` / `Xin chào`), trích dẫn `[n]` khớp chính xác từng nguồn và hỗ trợ **streaming SSE** (`POST /api/ask/stream`) khi bật LLM.
- **Thư viện công khai & Quản trị tách biệt bảo mật:**
  - Sinh viên đọc được toàn văn từng điều khoản quy chế công khai trên trang **Thư viện** (`/library` qua `GET /api/catalog/{rid}` đã làm sạch metadata).
  - Khu vực **Quản trị** (`/documents`) và toàn bộ `/api/documents/*` bảo vệ bằng `HV_API_TOKEN`; lịch sử hội thoại cô lập theo khóa sở hữu từng trình duyệt (`X-HocVu-Owner`).

---

## Cấu trúc mã nguồn (Single Source of Truth)

```text
├── artifacts/hocvu/
│   ├── src/          # Giao diện React/TypeScript (Vite + Tailwind + Radix UI)
│   ├── tests/        # Kiểm thử frontend (Vitest + Playwright)
│   ├── app/          # Backend Python/FastAPI duy nhất (core/, server/, migrations/, tests/)
│   ├── local_run.py  # Trình khởi chạy cục bộ (tự build UI & tạo token tạm nếu cần)
│   └── run.py        # Trình khởi chạy Replit Preview & Production
├── run.bat / run.sh  # Khởi chạy nhanh trên Windows / Linux / macOS
├── Dockerfile        # Build multi-stage (React + FastAPI)
├── pyproject.toml    # Phụ thuộc Python chuẩn (uv)
└── requirements*.txt # Manifest Python đồng bộ với artifacts/hocvu/app/
```

---

## Chạy cục bộ nhanh (Windows / Linux / macOS)

### 1. Cài đặt môi trường lần đầu
```bash
# Python 3.13 (khuyến nghị qua uv) hoặc pip
uv sync --python 3.13
# Hoặc: python -m pip install -r requirements.txt

# Node.js / pnpm (cài & build giao diện React)
pnpm install
pnpm --filter @workspace/hocvu run build
```

### 2. Khởi chạy ứng dụng
- **Windows:** Nhấn đúp [`run.bat`](run.bat) (tự mở trình duyệt tại `http://127.0.0.1:8000`).
- **Linux / macOS:**
  ```bash
  ./run.sh
  ```
- Nếu bạn chưa đặt `HV_API_TOKEN` trong tệp `.env`, trình khởi chạy cục bộ sẽ tự tạo **mật khẩu quản trị tạm** cho phiên chạy và in ra terminal để bạn đăng nhập `/documents` khi cần.

### 3. Bật AI diễn đạt, Cloud Embedding & STT dự phòng (tùy chọn)
Sao chép `.env.example` thành `.env` ở thư mục gốc (không commit lên Git):
```env
HV_API_TOKEN=mat-khau-quan-tri-cua-ban

# Tùy chọn AI diễn đạt & STT dự phòng (Gemini hoặc OpenAI)
HV_LLM=gemini
GEMINI_API_KEY=your-real-key
GEMINI_MODEL=gemini-3.8-flash

# Tìm kiếm ngữ nghĩa:
# - auto: dùng E5 cục bộ nếu đã cài, nếu không tự dùng Gemini/OpenAI Embedding API
# - local / gemini / openai
HV_SEMANTIC=1
HV_EMBEDDING_BACKEND=auto
```
Sau đó chạy lại `./run.sh --semantic` (hoặc đặt `HV_SEMANTIC=1` trong `.env`).

---

## Chạy bằng Docker

```bash
docker build -t hocvu-ai .
docker run -p 10000:10000 -e HV_API_TOKEN=change-me hocvu-ai
```

---

## Kiểm thử

```bash
# Kiểm thử backend Python (>550 bài test)
cd artifacts/hocvu/app && python -m unittest discover -s tests

# Kiểm thử frontend React (TypeScript + Vitest)
pnpm --filter @workspace/hocvu typecheck
pnpm --filter @workspace/hocvu test
pnpm --filter @workspace/hocvu build
```

---

## Triển khai trên Replit

Xem chi tiết vận hành Replit, lưu trữ bền vững PostgreSQL + App Storage và quy trình Publish tại [`artifacts/hocvu/README.md`](artifacts/hocvu/README.md) và [`artifacts/hocvu/app/docs/persistent-storage.md`](artifacts/hocvu/app/docs/persistent-storage.md).
