# Lưu trữ bền vững trên Replit

## Dữ liệu nào ở đâu?

| Dữ liệu | Nơi lưu khi `HV_STORAGE_BACKEND=replit` |
| --- | --- |
| PDF, DOCX, ảnh gốc và văn bản Unicode đã trích xuất | App Storage riêng tư, đối tượng bất biến kiểm tra bằng SHA-256 |
| Danh mục, ngày hiệu lực, bản sửa đổi kho tài liệu | PostgreSQL |
| Câu hỏi/trả lời đã lưu, căn cứ và đánh giá ban đầu, ngữ cảnh | PostgreSQL |
| Quyền sở hữu theo trình duyệt và dấu hội thoại đã xóa | PostgreSQL |
| Chỉ mục BM25/vector và bản tệp dùng để lập chỉ mục | Cache trong `HV_DATA_DIR`, có thể dựng lại |
| Tệp âm thanh tổng hợp | Cache tạm, có thể tạo lại; URL âm thanh cũ có thể hết tồn tại |

Không mở SQLite trực tiếp trên App Storage. Không dùng filesystem của bản
publish làm nguồn dữ liệu chính. Nếu PostgreSQL/App Storage không hoạt động,
ứng dụng báo lỗi, không âm thầm ghi dữ liệu mới vào ổ đĩa.

## Thiết lập và chuyển dữ liệu lần đầu

1. Trong Replit, mở **App Storage**, chọn **Create new bucket**, đặt tên rồi
   **Create bucket**. Xem **Bucket ID** trong Settings của bucket.
2. Đặt biến **không bí mật** `HV_STORAGE_BUCKET_ID` bằng ID đó, hoặc để trống
   nếu đã có bucket mặc định của dự án. `HV_STORAGE_PREFIX=hocvu/v1` phân vùng
   đối tượng của ứng dụng; không đổi prefix sau khi chuyển dữ liệu.
   `DATABASE_URL` do Replit quản lý, không chép vào mã nguồn hoặc chat.
3. Áp dụng schema trong **development**:

   ```sh
   python manage.py init-storage-schema
   ```

   Nguồn schema nằm trong `migrations/001_persistent_storage.sql`. Khi publish,
   Replit áp dụng chênh lệch schema development → production. Ứng dụng không
   chạy DDL khi khởi động và không có script tự sửa schema production.
4. Tạo bản sao lưu khi vẫn ở chế độ local:

   ```sh
   HV_STORAGE_BACKEND=local python manage.py backup-storage
   ```

   Bản ZIP được ghi với quyền `0600` vào `generated-artifacts/backups/`.
   Chứa tài liệu, văn bản trích xuất, lịch sử, quyền sở hữu, dấu đã xóa và bản
   SQLite nhất quán lấy bằng backup API, không chỉ chép `sessions.db`.
   Không chứa `.env`, API token, model tải về hoặc cache embedding.
5. **Dừng workflow máy chủ** trước khi chuyển để không bỏ sót lượt hỏi hay
   thao tác tài liệu phát sinh. Kiểm tra trước bằng:

   ```sh
   HV_STORAGE_BACKEND=local python manage.py migrate-storage --backup generated-artifacts/backups/TEN-BAN-SAO-LUU.zip
   ```

6. Áp dụng sau khi xác nhận nguồn:

   ```sh
   HV_STORAGE_BACKEND=local python manage.py migrate-storage \
     --backup generated-artifacts/backups/TEN-BAN-SAO-LUU.zip --apply --confirm
   ```

   Công cụ kiểm tra checksum, lưu thêm bản ZIP riêng tư trên App Storage,
   tải các tệp lên và xác minh lại, rồi mới commit metadata + lịch sử cùng
   một transaction PostgreSQL. Đích phải trống. Lặp lại cùng bản sao lưu
   không nhập trùng, không phục hồi hội thoại đã bị xóa sau lần nhập đầu.
   Nếu lỗi giữa chừng, bản local và bản sao lưu vẫn được giữ; đối tượng chưa
   được tham chiếu có thể còn trên App Storage nhưng không xuất hiện trong kho.
7. Đặt `HV_STORAGE_BACKEND=replit` và khởi động lại workflow. Kiểm tra trang
   quản lý báo **Lưu bền vững: App Storage + PostgreSQL**. Hỏi đáp vẫn công khai;
   API quản trị và bản sao lưu vẫn cần mật khẩu.

Chuyển dữ liệu từ workspace không đồng nghĩa đã lấy dữ liệu của một bản chạy
khác. Kiểm tra trạng thái publish trước khi chuyển; nếu có dữ liệu chỉ tồn tại
trên bản chạy khác, phải sao lưu từ đúng nguồn đó trước khi publish lại.

## Publish lần đầu và các lần sau

- Development và production có database riêng. Chỉ ở **lần thiết lập đầu**
  với đích production trống, dùng lựa chọn **Set up your production database
  with your current development data** trong Publishing để đưa dữ liệu vừa
  chuyển sang production. Chỉ áp dụng schema không tự sao chép các lượt hỏi.
- **Không bật tùy chọn ghi đè production bằng development ở những lần publish
  sau**: làm vậy sẽ thay dữ liệu thật bằng dữ liệu thử nghiệm.
- App Storage của cùng dự án dùng chung giữa development và production.
  Đối tượng tệp là bất biến, metadata chỉ tham chiếu đến các đối tượng đã xác
  minh, vì vậy bản database ban đầu có thể sử dụng cùng các tệp đó.
- Cấu hình cùng Bucket ID/prefix và `HV_STORAGE_BACKEND=replit` trong môi
  trường production; để Replit cấp kết nối database production.
- Với mô hình chỉ mục và giới hạn tần suất trong RAM hiện tại, ưu tiên một
  Reserved VM chạy một process. Reserved VM **không thay thế lưu trữ bền vững**.
  Các process khác có thể nhận bản sửa đổi kho mới và dựng lại chỉ mục ở lần
  đọc tiếp theo; giới hạn tần suất vẫn là theo process.
- Không tự publish bằng script. Người quản trị kiểm tra rồi chọn Publish.

## Sao lưu và khôi phục

- Trang **Quản lý tài liệu → Sao lưu dữ liệu** yêu cầu xác nhận vì chứa toàn bộ
  lịch sử. Chế độ replit lưu ZIP riêng tư trên App Storage và cho tải thêm bản
  cache về máy. Chế độ local cảnh báo cần tải về máy vì ZIP chưa bền vững.
- CLI `python manage.py backup-storage` dùng backend hiện tại. Bản ZIP có
  checksum; giữ bản riêng ngoài ứng dụng cho dữ liệu quan trọng.
- Đường dẫn tải ZIP trên ứng dụng chỉ trỏ đến cache hiện tại. Sau khi cache
  bị xóa/publish lại, lấy bản bền vững từ thư mục `hocvu/v1/backups/` trong
  App Storage. Không công khai bucket hay đường dẫn chứa lịch sử.
- Có thể dùng `migrate-storage --backup ... --apply --confirm` để khôi phục
  vào một database development mới, trống, rồi xác minh trước khi đưa lên
  production bằng luồng Publish. Công cụ không ghi đè database đang có dữ liệu
  và không chạy trong bản publish.
- Không tự gán phiên legacy chưa có owner cho một trình duyệt: dữ liệu vẫn
  được giữ nhưng không thể chứng minh ai sở hữu chỉ từ mật khẩu quản trị.
- Xóa tài liệu loại nó khỏi metadata và chỉ mục. Các blob bất biến cũ vẫn
  được giữ riêng tư để không làm hỏng bản sao lưu hoặc database môi trường kia.
  Chưa có tự động dọn blob/bản sao lưu; cần chính sách lưu giữ riêng trước khi
  xóa vật lý. Xóa lịch sử khỏi database không xóa các bản sao lưu đã tạo trước đó.

## Kiểm chứng trước khi dựa vào bản publish

1. Tải một tài liệu kiểm tra và hỏi câu có trích dẫn tài liệu đó.
2. Ghi nhận số tài liệu, lượt hỏi, quyền owner và dấu đã xóa.
3. Thử bằng thư mục cache mới/trống, giữ nguyên kết nối database và bucket:
   `HV_DATA_DIR=/tmp/hocvu-empty-cache HV_STORAGE_BACKEND=replit ...`.
4. Kiểm tra tệp được khôi phục, chỉ mục được dựng lại, căn cứ lịch sử giữ nguyên
   và trình duyệt khác vẫn không đọc được hội thoại.
5. Kiểm tra thêm/sửa/xóa, mất kết nối App Storage và rollback khi commit lỗi.

Kiểm thử PostgreSQL dùng schema ngẫu nhiên riêng, không sửa dữ liệu ứng dụng:

```sh
HV_STORAGE_BACKEND=local HV_TEST_POSTGRES=1 HV_SEMANTIC=0 \
  python -m unittest discover -s tests -v
```
