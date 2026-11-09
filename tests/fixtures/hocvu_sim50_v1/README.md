# HocVu AI — 50 văn bản mô phỏng kiểm thử

**DỮ LIỆU MÔ PHỎNG — KHÔNG CÓ GIÁ TRỊ ÁP DỤNG.**

Bộ fixture độc lập: 50 DOCX, 200 ca/đáp án kỳ vọng, manifest CSV/JSON và catalog. Mọi cơ quan, quy tắc và số liệu đều hư cấu. Không tự nhập vào ứng dụng hay dùng cho quyết định học vụ.

- [Hướng dẫn chi tiết và giới hạn tương thích](README_VI.md)
- [40 tài liệu nhập thử cơ bản](01_baseline_40/)
- [10 tình huống nâng cao — không nạp chung vào kho phục vụ](02_advanced_10/)
- [200 ca kiểm thử](evaluation/test_cases_200.json)
- [Danh mục và checksum](metadata/manifest.json)
- [Kiểm tra cấu trúc đã thực hiện](VALIDATION.json)

Nhập cơ bản trên môi trường development riêng, chia hai lô 20 tệp và nhập ngày áp dụng theo manifest. Tài liệu 047–050 phải giữ ngoài kho phục vụ. Trạng thái, phạm vi và ngày hết hiệu lực trong manifest chưa được uploader hiện tại tự thực thi.

Đã kiểm tra toàn vẹn DOCX, checksum, trích xuất văn bản và schema/chunk. **Chưa chạy đánh giá trả lời 200 câu, kiểm thử tải, OCR hoặc giọng nói.** Đây là dữ liệu regression/acceptance biên soạn mới, không phải benchmark độc lập đã được thẩm định.

Chỉ bổ sung fixture trong thư mục tests; không sửa mã ứng dụng, migration hoặc cấu hình triển khai.
