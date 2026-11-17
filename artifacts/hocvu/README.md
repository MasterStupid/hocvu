# HocVu AI trên Replit

Backend Python/FastAPI gốc nằm trong `app/`; giao diện mới được viết bằng React/TypeScript
ở `src/`. Giao diện HTML/CSS/JS cũ trong `app/ui/` được giữ để đối chiếu và kiểm thử,
không còn là giao diện đang chạy. Không dùng Netlify.

## Chạy bản xem trước

Workflow được quản lý: **artifacts/hocvu: web**.
Lệnh: `pnpm --filter @workspace/hocvu run dev`.
Replit truyền `PORT`; máy chủ lắng nghe `0.0.0.0` và phục vụ cả trang `/` lẫn `/api/*`.
Không chạy thêm máy chủ Express mẫu để phục vụ API HocVu.
Workflow build React bằng Vite vào `dist/public/` rồi FastAPI phục vụ bản build đó.
Sau khi chỉnh UI, restart workflow để build lại. Không có Vite proxy hoặc máy chủ frontend thứ hai.
Các trang: `/` hỏi đáp, `/library` danh mục công khai, `/documents` quản trị, `/settings` cài đặt.

Môi trường Python được quản lý ở thư mục gốc qua `pyproject.toml` và `uv.lock`.
`HV_SEMANTIC=0` dùng BM25 có sẵn, không tải mô hình embeddings.
Không có khóa LLM thì ứng dụng dùng chế độ trích xuất hiện có, không giả lập kết quả LLM.
`app/package.json` giữ phạm vi CommonJS cho các bài kiểm thử JavaScript gốc;
không để chúng kế thừa chế độ ESM của pnpm artifact cha.

## Quản trị và dữ liệu

### Kiểm thử frontend quản trị an toàn

Chạy từ workspace:

```sh
pnpm --filter @workspace/hocvu test
pnpm --filter @workspace/hocvu typecheck
```

Bộ kiểm thử `tests/` chạy React thật trong jsdom với Vitest/Testing Library,
mock ở lớp HTTP (`fetch`), không mock các hook, API client hoặc form quản trị.
Toàn bộ mật khẩu, tài liệu và tệp là dữ liệu tổng hợp. Không cần mật khẩu quản trị
thật, không gọi API đang chạy, không thay Secrets, không thay kho dữ liệu.
HTTP chưa có handler bị chặn trong mỗi bài kiểm thử để không rơi về mạng thật.

Các ca hồi quy bao gồm đăng nhập sai/đúng, đăng xuất xóa cache và hủy request,
upload nhiều tệp với metadata/OCR riêng, giới hạn 25 MB/tệp, 20 tệp và 50 MB/lô,
xem nội dung, sửa ngày, xác nhận/hủy xóa đơn/lô và tải backup có token.
Lỗi mạng/401/503 được kiểm tra riêng cho mutation và refetch sau commit;
mutation thất bại phải giữ dữ liệu nhập, còn commit thành công không được báo
như rollback hoặc giữ tệp để tải trùng. Đây là kiểm thử frontend cô lập,
không thay thế kiểm thử API FastAPI hoặc kiểm thử trình duyệt trên môi trường riêng.

### Kiểm thử quản trị trên Chromium cô lập

```sh
pnpm --filter @workspace/hocvu test:browser
```

Playwright tự mở frontend Vite riêng tại `127.0.0.1:4179` và đóng sau khi chạy.
Không cần khởi động workflow HocVu hoặc FastAPI. Nếu cổng đã bị chiếm, bài chạy
thất bại thay vì dùng lại một máy chủ không rõ nguồn. Không cấu hình URL backend,
không dùng mật khẩu thật và không thay Secrets để chạy kiểm thử.

Mỗi bài có browser context và kho dữ liệu tổng hợp riêng. Interception cấp context
được cài trước khi mở trang; API client, form, hooks và Radix vẫn là mã ứng dụng thật.
Yêu cầu quản trị phải có token tổng hợp mới được fixture chấp nhận.
API chưa có handler và kết nối ngoài bị chặn, đồng thời làm kiểm thử thất bại;
riêng Google Fonts nhận CSS rỗng ngay trong bộ kiểm thử, không tải qua mạng.
Máy chủ frontend cũng từ chối `/api/*` bằng 503 nếu interception bị thiếu.
Không có backend hay quyền truy cập kho tài liệu thật trong bộ kiểm thử.

Các bài kiểm tra file chooser nhiều tệp, chọn lại cùng tệp, multipart chứa byte thật,
ngày ISO/năm nhuận, xác thực `required` native, kéo thả với `DataTransfer`/`File`
của Chromium, giữ hàng đợi khi upload lỗi và retry, focus ban đầu/Tab/Shift+Tab/Escape
và trả focus khi đóng hộp thoại. Response gate giữ request đang chờ để kiểm tra
khóa upload/metadata, xóa đơn/lô, sao lưu và sửa ngày mà không dựa vào thời gian sleep.
Kéo thả được phát bằng DOM events trên trình duyệt thật; không giả lập kéo từ cửa sổ
quản lý tệp của hệ điều hành, và không tự động điều khiển giao diện lịch của hệ điều hành.
Hiện bộ này chỉ chạy Chromium desktop, không khẳng định tương thích Firefox/WebKit/mobile.

Replit dùng Chromium hệ thống ở `/repl/tools/bin/chromium` nếu có. Trên máy khác,
cài browser của Playwright bằng `pnpm --filter @workspace/hocvu exec playwright install chromium`,
hoặc truyền `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` trỏ đến Chromium đã cài (đây là
đường dẫn chương trình, không phải secret). Không cần thay Secrets của dự án.
Typecheck hiện kiểm tra cả cấu hình và mã kiểm thử trình duyệt.
Report HTML, screenshot và trace khi lỗi nằm ở `generated-artifacts/hocvu-browser/`
(đã bị loại khỏi Git và gói publish). Mở report bằng:

```sh
pnpm --filter @workspace/hocvu exec playwright show-report ../../generated-artifacts/hocvu-browser/report
```

- Trang hỏi đáp và shell React `/documents` công khai; dữ liệu/API quản trị vẫn yêu cầu xác thực.
- Đăng nhập quản trị trong React dùng `X-HocVu-Token`, chỉ giữ mật khẩu trong bộ nhớ,
  không lưu vào localStorage/sessionStorage. Bookmark cũ `/documents.html` vẫn có lớp HTTP Basic.
- Đặt **HV_API_TOKEN** trong Replit Secrets để chọn mật khẩu quản trị.
  Tài khoản HTTP Basic hiện có là `hocvu`.
- Chỉ ở môi trường xem trước, nếu chưa đặt `HV_API_TOKEN`, bộ chạy dùng
  `SESSION_SECRET` đang có để giữ API được bảo vệ. Không ghi hoặc hiển thị giá trị này;
  hãy đặt `HV_API_TOKEN` riêng nếu muốn đăng nhập quản trị.
- Bản xem trước dùng `HV_STORAGE_BACKEND=replit`: PostgreSQL lưu metadata/lịch sử,
  App Storage của chính dự án lưu tệp; `.local/hocvu-data/` chỉ là cache.
  Dữ liệu local cũ vẫn giữ nguyên, không tự nhập vào kho bền vững.
- Chưa chuyển dữ liệu từ hệ thống cũ và chưa tự nạp bộ 50 tài liệu mô phỏng.
  Kho mẫu có sẵn của ứng dụng vẫn là dữ liệu minh họa, không phải quy định chính thức.

## Trước khi publish

Bản xem trước chạy tại đây **không đồng nghĩa đã publish**.
Ứng dụng gốc yêu cầu `HV_STORAGE_BACKEND=replit`, PostgreSQL và App Storage
cho dữ liệu bền vững khi publish; xem `app/docs/persistent-storage.md`.
Cần cấu hình bucket thuộc **dự án này**, không dùng ID bucket trong cấu hình Replit cũ.
Cần đặt riêng `HV_API_TOKEN`. Bộ chạy cố ý không cho publish bằng chế độ local
hoặc dùng ngầm mật khẩu dự phòng của bản xem trước.

## Netlify

Không có tệp cấu hình hoặc đoạn mã Netlify trong mã nguồn gốc cần xóa.
Các deploy checks trên GitHub do kết nối Netlify bên ngoài tạo ra. Đổi máy chủ
sang Replit không tự ngắt kết nối ấy; chủ tài khoản cần unlink repository khỏi
các site Netlify cũ nếu muốn dừng hoàn toàn các checks tự động.
