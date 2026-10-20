# HocVu AI

HocVu AI is a Vietnamese, grounded voice assistant for looking up academic regulations. It implements the research proposal's core pipeline: a regulation knowledge base, chunking and retrieval, citation-backed answers with abstention, multi-turn session storage, browser voice input/output, and a repeatable retrieval evaluation.

## Run locally

On Windows, the quickest option is to double-click `run.bat`. It opens the
application in the browser and uses the fast local BM25 index by default.
Set `HV_SEMANTIC=1` before starting only when the optional embedding model has
already been installed or downloaded. Keep its terminal window open while
using the project; press `Ctrl+C` there to stop it.

```powershell
python manage.py ingest
python manage.py serve --open
```

Open `http://127.0.0.1:8000`. Use Chrome or Edge for Vietnamese browser speech recognition; text-to-speech uses the browser's Vietnamese voice when available.

The date field below the chat box is optional: choose it only when you need to
look up the regulation effective on a historical date. Leaving it blank always
uses the current date. Set a strong `HV_API_TOKEN` before starting the server.
API authentication is enabled for every launch mode, including direct ASGI
imports and local binds. API clients send `X-HocVu-Token`; with
`HV_BROWSER_AUTH=1`, browsers can instead use the native Basic login.
`/api/health` remains public. Missing credentials never open the API.

### Reverse proxies and request limits

The request limit (`HV_RATE_LIMIT_PER_MINUTE`, default 120) runs before
authentication, including invalid Basic/token attempts. HTTP 429 includes
`Retry-After`. Protected UI assets also count when browser login is enabled.

`HV_TRUSTED_PROXIES` is a comma-separated list of immediate/internal proxy IPs
or CIDRs. Only loopback (`127.0.0.1,::1`) is trusted by default; an empty value
trusts no proxy. Add the real proxy networks when hosting behind another
reverse proxy. The proxy must append the actual connecting client to
`X-Forwarded-For`. The app walks the chain from right to left, stopping at the
first untrusted hop. Never trust Internet-wide ranges or arbitrary forwarded
headers: direct clients cannot select their own rate-limit identity.

The bundled launcher disables Uvicorn's automatic proxy rewriting. For direct
ASGI launches, preserve the original transport peer the same way:

```bash
uvicorn server.app:app --host 0.0.0.0 --port 5000 --no-proxy-headers
```

Do not combine this app's proxy policy with upstream ASGI middleware/server
options that already replace `scope["client"]`. Limits are per process, not
shared between workers or replicas. Expired client buckets are reclaimed;
the bounded in-memory table rejects new clients at capacity instead of
evicting active buckets and resetting their quotas.

## AI-assisted answers and Live conversation

The **AI** switch on the main page is off by default. When enabled, the
system first retrieves grounded excerpts, then asks the configured LLM to make
the answer more natural for speech. Citations still come from the local
retrieval result. If no LLM key is configured or the request fails, HocVu AI
keeps the extractive answer and labels it as a fallback.

To enable the optional Gemini integration, place these variables in the local
`.env` file (it is ignored by Git) or set them in the current PowerShell
session before starting the server:

```powershell
$env:HV_LLM = "gemini"
$env:GEMINI_API_KEY = "your_api_key"
# Optional: $env:GEMINI_MODEL = "gemini-3.8-flash"
python manage.py serve
```

OpenAI Responses remains available by setting `HV_LLM=openai` and
`OPENAI_API_KEY` instead.

When the AI switch is on, the user's question and only the retrieved excerpts
for that turn are sent to the configured LLM provider. Do not enable it for
sensitive documents unless that data transfer is approved.

Select **Live** to start a hands-free dialogue: after the first user click and
microphone permission, the browser listens, sends a turn, reads the response,
then opens the microphone for the next turn. This uses the browser's speech
recognition and speech synthesis; browser vendors may process speech according
to their own privacy settings. Audio is not uploaded to this Python server.

**Mới** starts a separate conversation without deleting saved turns.
**Xóa lịch sử** asks for confirmation, then permanently removes all saved turns
of the current session only and opens a fresh conversation with an empty source
panel. Canceling or a failed request keeps the current conversation visible.
Deletion is unavailable while that conversation is loading or awaiting an answer.
The `DELETE /api/history?session_id=...` API requires exactly one explicit,
nonempty session ID. Legacy names (including Unicode, spaces and punctuation)
are matched exactly, never trimmed or interpreted as wildcards. It uses the
existing authentication, origin checks and rate limit, and is idempotent for a
session with no saved turns or an already-deleted session. It does not remove
downloaded exports.

Deleted session IDs are permanently closed (including IDs with no saved turns).
An in-flight answer cannot recreate deleted turns: closing the ID and removing
its turns are atomic with respect to saving answers, even across server
processes sharing the SQLite database. A new or interrupted `POST /api/ask`
using a closed ID receives HTTP **410** with `code: "session_closed"` and must
use a fresh ID (or omit `session_id`); the server never silently reuses the old
ID. Reading its history still returns `[]`, and repeated deletion is safe.
`GET /api/history/status?session_id=...` returns `{session_id, closed}` under
the existing access controls. Do not prune closed IDs independently of clients:
they prevent delayed requests from resurrecting deleted data.

Tabs on the same browser origin notify one another after successful deletion,
clearing only the deleted conversation, stopping its voice playback and ignoring
late answers/history. Starting **Mới** in one tab does not switch another tab.
On startup or returning to a tab, the UI also checks server status to detect
deletions by API clients or missed notifications. Failed checks leave the
current view intact; the server still rejects writes to a closed ID.

DOCX works with the Python standard library. Install the dependencies before the first run:

```powershell
python -m pip install -r requirements.txt
```

The first index build downloads `intfloat/multilingual-e5-small` for local
Vietnamese semantic retrieval (approximately 500 MB for model weights, in
addition to the AI runtime). The application falls back to keyword search if
the model cannot be downloaded. Set `HV_EMBEDDING_MODEL` to use a different
Sentence Transformers model.

Passage embeddings are cached under `HV_DATA_DIR/models/embeddings` (by default
`data/models/embeddings`). Unchanged server starts and CLI commands reuse them;
the model still loads to encode new questions. Changes to passage text/order,
chunking rules/settings, the embedding model, or encoder/runtime versions
produce a new cache. Missing or corrupt caches rebuild automatically. Cache
write failures are reported through the existing semantic status while search
continues with in-memory vectors. These are disposable derived files: stop
semantic-search processes before manually clearing the directory to free disk
space. Old cache generations are retained, not automatically pruned.
`HV_SEMANTIC=0` does not read or write embedding caches or load embedding libraries.

## Add and manage regulations

Open **Quản lý tài liệu** from the top navigation or visit `http://127.0.0.1:8000/documents.html`. Select multiple PDF, DOCX or image files (up to 25 MB each), set the order number, decision number, article/clause and effective date for each file, then upload the queue. The page immediately rebuilds the retrieval index, can show the normalized extracted text and number of indexed chunks, and supports selecting and removing queued or previously uploaded files. Encrypted PDFs are rejected.

Enable **OCR tiếng Việt** for a screenshot/photo, scanned PDF, or DOCX containing scanned images. OCR runs locally with Tesseract: image files are read entirely; PDF OCR runs only on pages without a usable text layer; and DOCX OCR reads images embedded in the file. It works best with clear, upright Vietnamese text. PDFs/DOCX with normal selectable text keep their native extraction.

The upload field **Điều / khoản** supplies the citation locator for the uploaded excerpt, for example `Điều 4, Khoản 2`. Its sections and chunk fragments retain that locator rather than being assigned new legal clause numbers. Leave it empty to keep automatically detected sections; other free-form locators are preserved as entered.

Scanned-only PDFs are also detected automatically; enabling OCR additionally fills scan pages in mixed text/image PDFs. Document extraction never sends PDF page images to Gemini or another cloud model, regardless of `HV_LLM` or `GEMINI_API_KEY`. Those settings apply separately to optional AI answer rewriting, not OCR. OCR does not summarize the source or impose an LLM output-token limit. Older cached extractions are rebuilt from the original files when their extraction version is upgraded.


### Phục hồi ngày sai của tài liệu cũ

Lệnh sau **chỉ đọc metadata**, không OCR, không ghi nội dung tài liệu vào log,
không tự khôi phục manifest từ bản sao lưu, và không đoán ngày thay thế:

```sh
python manage.py audit-document-dates
```

Kết quả JSON cho biết `total`, `affected_count`, các mã `id`/`rid` bị ảnh hưởng
và `manifest_sha256`. Ngày không tồn tại (ví dụ 31/02), sai định dạng hoặc sai
kiểu dữ liệu đều được báo. Ngày trống/không có vẫn dùng ngày tải lên như trước;
ngày hợp lệ trong tương lai không phải là lỗi. Lệnh chỉ kiểm tra thư mục dữ liệu
của môi trường đang chạy (`HV_DATA_DIR`), không kiểm tra một bản cài đặt khác.

Quản trị viên kiểm tra tài liệu gốc và xác nhận ngày áp dụng chính xác.
Tạo `data/date-repairs.json` (không đưa vào Git), chỉ chọn những tài liệu cần sửa:

```json
{
  "manifest_sha256": "chép nguyên mã từ kết quả rà soát",
  "corrections": [
    {"id": "mã id đầy đủ của tài liệu bị ảnh hưởng", "document_date": "2026-02-28"}
  ]
}
```

Xem trước, không ghi dữ liệu:

```sh
python manage.py repair-document-dates --plan data/date-repairs.json
```

Trước khi áp dụng, **dừng máy chủ và mọi tiến trình ghi dữ liệu** (kể cả máy chủ
khởi chạy trực tiếp bằng Uvicorn), sao lưu thư mục dữ liệu. Chạy trên đúng môi
trường chứa tài liệu; chỉ người quản trị có quyền truy cập shell nên chạy lệnh.
`--confirm` xác nhận các ngày đã được quản trị viên kiểm tra, không phải ngày
do công cụ tự chọn:

```sh
python manage.py repair-document-dates --plan data/date-repairs.json --apply --confirm
```

Lệnh luôn báo số bị ảnh hưởng trước. Manifest thay đổi sau khi lập kế hoạch,
mã không tồn tại/trùng, ngày thay thế không hợp lệ và tài liệu vốn không bị lỗi
đều bị từ chối. Công cụ dựng chỉ mục tạm qua engine, kiểm tra tìm kiếm không thấy
tài liệu trước ngày áp dụng và thấy tài liệu đúng/sau ngày đó rồi mới lưu.
Kiểm tra dùng BM25 ngoại tuyến, không cần tải mô hình hoặc gửi câu hỏi đến LLM.
Tệp gốc, bản trích xuất, mã tài liệu và mọi metadata khác giữ nguyên; tài liệu
không được chọn không đổi. Lỗi dựng/kiểm tra không ghi metadata/chỉ mục; lỗi
ghi thông thường được hoàn tác. Các tệp `.bak` giữ manifest và chỉ mục trước khi
phục hồi. Không ngắt tiến trình trong lúc lưu; nếu mất điện/dừng cưỡng bức, giữ
máy chủ dừng, khôi phục cả manifest/chỉ mục từ bản sao lưu đã tạo trước khi chạy
và rà soát lại. **Khởi động lại máy chủ** sau thành công để nạp chỉ mục mới.
Chạy lại lệnh rà soát để biết số tài liệu còn cần xác nhận ngày.

## Deploy: Netlify + Render

The browser interface is static, but document upload, OCR, the search index,
and conversation storage require Python and a writable disk. This repository
therefore deploys the **UI on Netlify** and the **API on Render**. The Netlify
proxy keeps the API token out of the browser.

1. Push this repository to GitHub, then on Render choose **New → Web Service**
   and connect the repository. Select the included `Dockerfile`; Render will
   use it automatically. Set the health check path to `/api/health`.
2. In Render's environment variables, add a strong random `HV_API_TOKEN`, set
   `HV_SEMANTIC=0`, and set `HV_DATA_DIR=/var/data`. If using the optional AI
   rewriting switch, also add `HV_LLM=gemini`, `GEMINI_API_KEY`, and optionally
   `GEMINI_MODEL=gemini-3.8-flash`.
3. Attach a Render persistent disk mounted at `/var/data`. This is required to
   keep uploaded documents, the OCR output, index, and chat database across
   deploys. Without it, Render's filesystem is temporary and the knowledge
   base is reset whenever the service is rebuilt or restarted.
4. After Render is live, copy its HTTPS address, such as
   `https://hocvu-api.onrender.com`. On Netlify choose **Add new site → Import
   an existing project**, select the same GitHub repository, and leave the
   build settings to `netlify.toml`.
5. In Netlify's **Environment variables**, set `HOCVU_API_URL` to the Render
   HTTPS address (without a trailing slash) and `HOCVU_API_TOKEN` to the exact
   same value as `HV_API_TOKEN` on Render. Trigger a new deploy.
6. Copy the Netlify site's address, such as `https://hocvu.netlify.app`, and
   add it on Render as `HV_TRUSTED_ORIGINS` (comma-separate multiple exact
   origins, no wildcards or paths). Redeploy Render. Without it, the API
   rejects proxied questions, uploads, deletes, and reindexing to prevent other
   websites from using the Netlify proxy's token.

Netlify publishes the `ui` directory and rewrites every `/api/*` request to
Render with the private `X-HocVu-Token` header. Do not put either token in
`ui/*.js`, a committed `.env` file, or the public site settings.

The demonstration regulations are generated from source code on the first
startup. Files uploaded only to your old local `data/` folder are not committed
to Git and will not appear in the cloud automatically; upload them again from
the **Quản lý tài liệu** page after the first deployment.

## Research workflow

```powershell
python manage.py ask "Điều kiện bảo lưu kết quả học tập là gì?"
python manage.py evaluate
```

`evaluate` writes `data/eval_result.json`, reporting citation-grounding accuracy and refusal accuracy. The existing `grounded_retrieval_accuracy` checks regulation IDs only. The additional `article_grounded_retrieval_accuracy` requires one citation to match both the expected regulation and article; `article_grounded_retrieval_total` counts the annotated, non-refusal questions included. Rows retain `correct` for the legacy check and add `expected_aids`, paired `cited_articles`, and `article_correct` (`null` for refusal questions or questions without article annotations). These metrics check for at least one matching citation, not the correctness of every claim or every citation. WER, TTS quality, response latency, and user satisfaction must be recorded with real participant data during the pilot, as stated in the proposal.

## Important data note

The bundled corpus is intentionally labelled demonstration data. It is not an official regulation database and must be replaced and reviewed by the university before real-world use. The system is designed to abstain when it lacks enough relevant evidence rather than invent a rule.

## Architecture

```text
Student text or voice
        | (browser STT)
        v
Intent and safety gate -> Vietnamese tokenization -> Hybrid BM25 + AI embedding retrieval
                                                   -> grounded answer + citations
        ^                                                               |
        +------------------------ SQLite session <---------------------+
                                                                        |
                                                            browser TTS v
```
