---
name: Ranh giới lưu trữ HocVu
description: Yêu cầu về nguồn dữ liệu và thiết lập cloud khi chuyển sang lưu bền vững
---

Chỉ sử dụng bucket thuộc chính dự án HocVu hiện tại; không lấy bucket ID từ
dự án cũ và không tự chuyển dữ liệu hiện hữu.

**Why:** Người dùng yêu cầu thiết lập kho bền vững mới mà không tự nhập dữ liệu
cũ, không tự publish và không chạy DDL production.

**How to apply:** Khởi tạo kho mới trống là một nhánh riêng với việc chuyển dữ
liệu, không tự chạy khi merge hay khởi động ứng dụng. Mọi lần nhập hoặc khôi
phục dữ liệu cũ cần yêu cầu rõ ràng của người dùng.
