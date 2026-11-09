# HocVu AI trên Replit

Mã ứng dụng Python/FastAPI gốc nằm trong `app/`; giao diện HTML/CSS/JS gốc được giữ nguyên.
Không dùng Netlify hoặc viết lại ứng dụng sang React. Các tệp React của bộ khung không
tham gia chạy ứng dụng.

## Chạy bản xem trước

Workflow được quản lý: **artifacts/hocvu: web**.
Lệnh: `pnpm --filter @workspace/hocvu run dev`.
Replit truyền `PORT`; máy chủ lắng nghe `0.0.0.0` và phục vụ cả trang `/` lẫn `/api/*`.
Không chạy thêm máy chủ Express mẫu để phục vụ API HocVu.

Môi trường Python được quản lý ở thư mục gốc qua `pyproject.toml` và `uv.lock`.
`HV_SEMANTIC=0` dùng BM25 có sẵn, không tải mô hình embeddings.
Không có khóa LLM thì ứng dụng dùng chế độ trích xuất hiện có, không giả lập kết quả LLM.
`app/package.json` giữ phạm vi CommonJS cho các bài kiểm thử JavaScript gốc;
không để chúng kế thừa chế độ ESM của pnpm artifact cha.

## Quản trị và dữ liệu

- Trang hỏi đáp công khai; `/documents.html` và API quản trị vẫn yêu cầu xác thực.
- Đặt **HV_API_TOKEN** trong Replit Secrets để chọn mật khẩu quản trị.
  Tài khoản HTTP Basic hiện có là `hocvu`.
- Chỉ ở môi trường xem trước, nếu chưa đặt `HV_API_TOKEN`, bộ chạy dùng
  `SESSION_SECRET` đang có để giữ API được bảo vệ. Không ghi hoặc hiển thị giá trị này;
  hãy đặt `HV_API_TOKEN` riêng nếu muốn đăng nhập quản trị.
- Bản xem trước dùng `HV_STORAGE_BACKEND=local` và dữ liệu ở
  `.local/hocvu-data/` của workspace. Không đưa dữ liệu chạy thử vào Git.
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
