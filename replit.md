# HocVu AI

Ứng dụng tra cứu quy chế đào tạo với giao diện React/TypeScript và backend FastAPI hiện có.

## Run & Operate

- Workflow **artifacts/hocvu: web** chạy `pnpm --filter @workspace/hocvu run dev`.
- Máy chủ Python duy nhất phục vụ giao diện `/` và API `/api/*`, dùng `PORT` do artifact cung cấp.
- `pnpm --filter @workspace/hocvu run build` build React bằng Vite và kiểm tra biên dịch Python.
- Workflow build frontend trước khi khởi chạy FastAPI; sau khi sửa UI cần restart workflow để cập nhật bản xem trước.
- `pnpm --filter @workspace/hocvu run typecheck` kiểm tra frontend TypeScript.
- Kiểm thử gốc: `cd artifacts/hocvu/app && python -m unittest discover -s tests`.
- Máy chủ Express mẫu được chuyển sang `/__template-api`; không dùng nó cho API HocVu.

## Stack

- React/TypeScript, Vite, React Query, backend Python 3.13/FastAPI/Uvicorn.
- BM25 mặc định (`HV_SEMANTIC=0`), không yêu cầu LLM để chạy tra cứu.
- Python dependencies ở `pyproject.toml` và `uv.lock` trong workspace.
- pnpm workspace chỉ cung cấp lệnh khởi chạy và quản lý artifact.

## Where things live

- `artifacts/hocvu/src/`: giao diện React, API client và quản lý trạng thái.
- `artifacts/hocvu/app/`: backend ứng dụng gốc, kiểm thử và giao diện cũ giữ để đối chiếu.
- `artifacts/hocvu/run.py`: bộ chạy tích hợp môi trường Replit.
- `artifacts/hocvu/README.md`: hướng dẫn chạy, quản trị và điều kiện publish.
- `artifacts/hocvu/app/docs/persistent-storage.md`: thiết kế lưu trữ bền vững hiện có.
- `dist/public/` là giao diện đang được FastAPI phục vụ; không phục vụ mã nguồn hoặc secret.

## Architecture decisions

- Giữ backend và phân quyền API khi thay toàn bộ giao diện bằng React theo yêu cầu người dùng.
- Trang quản trị React `/documents` chỉ là shell công khai; dữ liệu quản trị vẫn bắt buộc token.
- Giữ khóa định danh hội thoại cũ để không làm mất khả năng truy cập lịch sử sau khi đổi giao diện.
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
