---
name: Cô lập kiểm thử trình duyệt quản trị
description: Lý do kiểm thử quản trị phải độc lập với backend và dữ liệu thật
---

Giữ bộ hồi quy trình duyệt quản trị độc lập với backend thật; không dùng mật khẩu
quản trị thật, đổi Secrets hay bỏ phân quyền để kiểm thử.

**Why:** Người dùng yêu cầu kiểm tra các thao tác có thể sửa/xóa tài liệu mà không
gọi mutation lên kho tài liệu thật. Bộ này chứng minh hành vi trình duyệt, không
chứng minh tính đúng đắn hoặc độ bền vững của backend.

**How to apply:** Khi mở rộng kiểm thử trình duyệt, dùng dữ liệu tổng hợp và chặn
HTTP theo nguyên tắc không có handler thì thất bại. Kiểm thử hợp đồng/backend
phải có môi trường cô lập riêng, không chuyển các bài này sang kho đang sử dụng.
