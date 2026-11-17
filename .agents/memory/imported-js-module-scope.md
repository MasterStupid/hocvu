---
name: Phạm vi module khi nhập JavaScript cũ
description: Khác biệt Node.js khi chạy bài kiểm thử CommonJS của ứng dụng cũ trong artifact ESM
---

Giữ phạm vi module của ứng dụng JavaScript được nhập tách biệt khỏi artifact ESM cha.

**Why:** Các module UMD `.js` gốc có nhánh `module.exports`. Khi kế thừa `"type": "module"` từ artifact cha, Node nạp chúng như ESM; `require()` có thể trả namespace rỗng thay vì báo lỗi rõ ràng, khiến nhiều bài kiểm thử giao diện cùng hỏng dù trình duyệt vẫn chạy.

**How to apply:** Khi di chuyển ứng dụng cũ trong workspace, kiểm tra phạm vi package trước khi sửa logic giao diện để xử lý các lỗi export hoặc mock request bất thường.
