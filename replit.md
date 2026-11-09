# HocVu AI

Ứng dụng tra cứu quy chế đào tạo, nhập nguyên ứng dụng FastAPI và giao diện HTML/CSS/JS hiện có.

## Run & Operate

- Workflow **artifacts/hocvu: web** chạy `pnpm --filter @workspace/hocvu run dev`.
- Máy chủ Python duy nhất phục vụ giao diện `/` và API `/api/*`, dùng `PORT` do artifact cung cấp.
- `pnpm --filter @workspace/hocvu run build` kiểm tra biên dịch Python.
- Kiểm thử gốc: `cd artifacts/hocvu/app && python -m unittest discover -s tests`.
- Máy chủ Express mẫu được chuyển sang `/__template-api`; không dùng nó cho API HocVu.

## Stack

- Python 3.13, FastAPI/Uvicorn, giao diện tĩnh gốc.
- BM25 mặc định (`HV_SEMANTIC=0`), không yêu cầu LLM để chạy tra cứu.
- Python dependencies ở `pyproject.toml` và `uv.lock` trong workspace.
- pnpm workspace chỉ cung cấp lệnh khởi chạy và quản lý artifact.

## Where things live

- `artifacts/hocvu/app/`: mã nguồn ứng dụng gốc, các bài kiểm thử và tài liệu.
- `artifacts/hocvu/run.py`: bộ chạy tích hợp môi trường Replit.
- `artifacts/hocvu/README.md`: hướng dẫn chạy, quản trị và điều kiện publish.
- `artifacts/hocvu/app/docs/persistent-storage.md`: thiết kế lưu trữ bền vững hiện có.
- Không thay thế giao diện này bằng mã React mẫu trong artifact.

## Architecture decisions

- Giữ nguyên ứng dụng và cơ chế phân quyền cũ trong lần nhập này.
- Bản xem trước dùng SQLite/tệp local ở `.local/hocvu-data/`, không phải dữ liệu production.
- Chưa chuyển kho dữ liệu cũ hoặc tự nhập bộ tài liệu mô phỏng vào kho hỏi đáp.

## Product

- Tra cứu quy chế, câu hỏi gợi ý, hội thoại theo trình duyệt, trích dẫn và giọng nói.
- Quản trị tài liệu được bảo vệ bằng token hoặc HTTP Basic.

## Gotchas

- Không bỏ xác thực để kiểm thử trang quản trị.
- Đặt `HV_API_TOKEN` riêng trong Secrets nếu cần đăng nhập bằng tài khoản `hocvu`.
- Bản xem trước dùng `SESSION_SECRET` hiện có để bảo vệ API khi chưa có token riêng.
  Không đọc/hiển thị giá trị secret hoặc đưa chúng vào mã nguồn.
- Publish cần token riêng, PostgreSQL và bucket App Storage của dự án này;
  ứng dụng từ chối dùng backend local khi publish. Không dùng ID bucket từ dự án cũ.

## Pointers

- Metadata artifact phải được cập nhật qua công cụ kiểm tra schema, không sửa trực tiếp TOML thật.
