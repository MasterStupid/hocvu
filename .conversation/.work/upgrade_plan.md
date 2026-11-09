# KẾ HOẠCH NÂNG CẤP TOÀN DIỆN HỌC VỤ AI

Phiên bản: 1.0 | Ngày: 09/11/2026 | Trạng thái: Đề xuất để chốt phạm vi

## 1. Định hướng và phạm vi

Mục tiêu là nâng HocVu AI từ hệ thống phục vụ đồ án với dữ liệu minh họa thành trợ lý tra cứu quy chế có thể thử nghiệm có kiểm soát tại nhà trường: đúng nguồn, đúng thời điểm, bảo vệ lịch sử và có người chịu trách nhiệm duyệt nội dung.

Khuyến nghị: nâng cấp từng phần trên nền FastAPI và giao diện hiện có; không viết lại toàn bộ, không tách microservice và không bật truy xuất ngữ nghĩa hay LLM đại trà chỉ vì chúng mới hơn. Mỗi thay đổi phải chứng minh lợi ích trên bộ đánh giá độc lập và không làm giảm tính đúng đắn của căn cứ.

Nguồn lực người dùng xác nhận: nhóm nhỏ triển khai thử. Khung phân công đề xuất để ước lượng: hai người phát triển (một phụ trách backend/RAG, một phụ trách frontend/full-stack), QA/vận hành kiêm nhiệm; một cán bộ nghiệp vụ hỗ trợ duyệt tài liệu và đáp án; một người quyết định cho thử nghiệm. Số người và mức dành thời gian cụ thể chưa được xác nhận. Đối tượng đọc là nhóm phát triển, người hướng dẫn và cán bộ phụ trách triển khai. Kế hoạch phục vụ quyết định phạm vi, thứ tự làm và điều kiện đưa vào dùng thử, không phải cam kết ngày ra mắt.

Phạm vi gồm dữ liệu, tìm kiếm/RAG, hội thoại, giọng nói, trải nghiệm người dùng, quản trị, bảo mật, lưu trữ, kiểm thử, giám sát và triển khai. Chưa bao gồm tra cứu hồ sơ cá nhân, đăng ký học phần, quyết định học vụ tự động, ứng dụng di động native hoặc phục vụ nhiều trường trong cùng một hệ thống.

## 2. Căn cứ hiện trạng và giới hạn xác minh

Đã kiểm tra lại nhánh origin/main của kho MasterStupid/hocvu; tại thời điểm lập kế hoạch vẫn ở commit 3f35189. Đây là đánh giá mã nguồn và kết quả thực nghiệm đã kiểm tra trong đợt sửa báo cáo, không phải kiểm tra cấu hình hay chất lượng của một bản triển khai đang chạy. Chưa chạy lại toàn bộ kiểm thử, đo tải, WER, MOS hoặc SUS trong lần lập kế hoạch này.

| Hạng mục | Hiện trạng có căn cứ | Hướng nâng cấp |
| --- | --- | --- |
| Nền tảng | FastAPI/Uvicorn, giao diện tĩnh cùng nguồn; tách module core/server/ui. [S1] | Giữ kiến trúc đơn khối có module; thêm hợp đồng dữ liệu và ranh giới dịch vụ. |
| Kho tri thức | Có tải PDF/DOCX/ảnh, OCR, trích xuất, chỉnh ngày, lập lại chỉ mục; build_index ghép dữ liệu minh họa với tài liệu tải lên. [S2] | Tách kho demo/thật và thêm quy trình duyệt trước công bố. |
| Truy xuất | BM25, embedding tùy chọn, ngưỡng bằng chứng, xử lý hội thoại và ngày hiệu lực. [S2, S3] | Đánh giá độc lập, tối ưu truy xuất và chỉ bật hybrid nếu vượt baseline. |
| LLM | Có diễn đạt lại qua OpenAI/Gemini, timeout và fallback khi lỗi; engine nhận văn bản rewrite để dùng làm câu trả lời. [S2, S4] | Thêm hậu kiểm nội dung sau rewrite, không coi prompt là bảo đảm đúng. |
| Quyền truy cập | Hỏi đáp công khai; quản trị bằng token/Basic; lịch sử theo khóa trình duyệt; chống ghi chéo nguồn và giới hạn tần suất theo process. [S1, S5] | Danh tính quản trị riêng, phân quyền và nhật ký hành động. |
| Lưu trữ | Có local SQLite và chế độ Replit với PostgreSQL/App Storage, backup/import, kiểm tra revision. [S6] | Kiểm chứng cấu hình thực tế, diễn tập khôi phục, chính sách lưu giữ. |
| Giọng nói | STT phụ thuộc trình duyệt; TTS dùng Edge TTS và cache tệp. [S1, S7] | Tương thích thiết bị, đo chất lượng và kiểm soát lưu âm thanh. |

Trong bộ dữ liệu minh họa đã tái lập ở báo cáo, BM25 đạt 43/43 câu đúng cấp điều của Nhóm A, 16/20 câu Nhóm B, 6/8 hội thoại Nhóm C và 8/10 tình huống Nhóm D. Hybrid dùng bộ mã hóa NumPy đạt lần lượt 42/43, 16/20, 5/8 và 8/10. Các mẫu số và tiêu chí khác nhau; không gộp thành một tỷ lệ chung. Kết quả này không chứng minh hiệu quả trên tài liệu chính thức, và chưa phải benchmark PyTorch khi triển khai.

Vấn đề ưu tiên không phải “thiếu AI”, mà là bảo đảm tài liệu được phép sử dụng, điều kiện áp dụng đúng và chất lượng đo được khi thay dữ liệu.

## 3. Kết quả mong muốn và nguyên tắc ưu tiên

Kết quả O1 — Tin cậy: câu trả lời tra cứu nội dung phải bám vào văn bản đã duyệt, có nguồn mở được và ngày áp dụng rõ ràng; chào hỏi và thông báo hệ thống không cần trích dẫn quy chế.

Kết quả O2 — Dùng được: sinh viên tìm được thông tin hoặc biết phải hỏi lại/chuyển tới đơn vị nào; lỗi giọng nói không làm mất câu hỏi và không ngăn hỏi bằng chữ.

Kết quả O3 — Quản trị được: biết ai đưa tài liệu lên, ai duyệt, phiên bản nào đang dùng; có rollback và khôi phục đã diễn tập.

Kết quả O4 — Đánh giá được: mọi bản phát hành có commit, phiên bản dữ liệu/chỉ mục, cấu hình và báo cáo kiểm thử; không ghi số đo chưa có thành kết quả.

P0 là điều kiện bắt buộc trước thử nghiệm thật: dữ liệu được duyệt, không lẫn demo, bảo vệ truy cập, đối chứng chất lượng, lưu trữ bền vững và khôi phục. P1 làm cho thử nghiệm hữu ích và vận hành được. P2 chỉ thực hiện sau khi P0/P1 đạt yêu cầu và có bằng chứng về nhu cầu. Không chấm điểm RICE bằng số người dùng giả định khi chưa có analytics.

## 4. Kiến trúc đích đề xuất

Giữ giao diện web cùng nguồn với FastAPI. Bên trong tách các lớp: HTTP/xác thực → điều phối hội thoại → truy xuất → lựa chọn bằng chứng → tạo trả lời → hậu kiểm → lưu kết quả có căn cứ. Tiến trình xử lý tài liệu tách khỏi request hỏi đáp, dùng hàng đợi công việc bền vững trong PostgreSQL khi triển khai tính năng này.

PostgreSQL lưu metadata tài liệu, trạng thái duyệt, tài khoản/vai trò, lịch sử theo quyền, job và audit. App Storage giữ tệp gốc và bản trích xuất bất biến. Chỉ mục là sản phẩm có thể dựng lại từ bản dữ liệu đã duyệt; mỗi snapshot có manifest/checksum. Giữ hướng lưu trữ đang có, không chuyển database chỉ để đổi công nghệ.

API hỏi đáp sử dụng một snapshot nhất quán trong suốt lượt hỏi. Worker chuẩn bị chỉ mục mới, chạy kiểm tra rồi chuyển con trỏ snapshot nguyên tử; chỉ mục cũ còn dùng được nếu job mới lỗi. Bổ sung phiên bản hợp đồng API và kiểm thử tương thích giao diện, không đổi payload hàng loạt trong một lần.

Chưa cần vector database, Redis hoặc Kubernetes. Xem xét pgvector hay chỉ mục vector riêng sau khi benchmark cho thấy truy xuất hiện tại không đạt chất lượng/độ trễ ở quy mô mục tiêu. Khi chạy nhiều instance, phải thay giới hạn tần suất theo process bằng cơ chế chia sẻ, kiểm chứng cache/revision và giới hạn kết nối trước khi tăng số bản chạy.

## 5. Chương trình A — Kho tri thức chính thức và quản trị dữ liệu

1. Tách rõ chế độ demo và official; bản thử nghiệm thật từ chối khởi động nếu cấu hình trộn dữ liệu mẫu trái chính sách. Nhãn “minh họa” không thay thế việc tách kho.
2. Thêm vòng đời: nháp → chờ duyệt → đã công bố → thu hồi/lưu trữ. Trạng thái công bố và thời gian hiệu lực là hai thuộc tính độc lập: tài liệu đã công bố nhưng chưa tới ngày có hiệu lực không được dùng cho câu hỏi hiện tại.
3. Chuẩn hóa metadata: đơn vị ban hành, mã văn bản, phạm vi trường/khóa/ngành/đối tượng, ngày ban hành, ngày có hiệu lực/hết hiệu lực, quan hệ sửa đổi/thay thế, URL nguồn, hash tệp, người duyệt và thời điểm duyệt.
4. Có màn hình đối chiếu PDF/ảnh gốc với văn bản OCR theo trang. Cảnh báo chất lượng OCR thấp, thiếu trang và số liệu nghi ngờ; bắt buộc người duyệt kiểm tra các ngưỡng điểm, tỷ lệ, tín chỉ, thời hạn. Không dùng điểm OCR như bằng chứng nội dung đúng.
5. Trích xuất theo chương/điều/khoản/điểm, giữ trang gốc và vị trí đoạn. Với bảng, giữ quan hệ hàng/cột, tiêu đề và chú thích; không nối các ô thành câu làm đổi điều kiện.
6. Dò trùng bằng checksum và mã/phiên bản; phát hiện thời gian hiệu lực chồng lấn, sửa đổi từng phần và xung đột phạm vi. Không tự lấy “tài liệu mới nhất” để thay toàn bộ văn bản cũ.
7. Hiển thị bản diff và danh sách điều bị ảnh hưởng trước công bố. Cán bộ xác nhận nội dung; người phát triển không tự quyết văn bản nào có hiệu lực pháp lý.

Nghiệm thu: tệp chưa duyệt không xuất hiện trong retrieval, catalog công khai hoặc gợi ý; tài liệu bị thu hồi không được dùng cho câu hỏi hiện tại; truy vấn lịch sử chọn đúng snapshot thời điểm; mở nguồn được tới trang/đoạn đã trích.

## 6. Chương trình B — Truy xuất, lập luận và sinh câu trả lời

Tách quy trình tìm ứng viên khỏi bước quyết định có đủ bằng chứng. So sánh tối thiểu BM25 hiện tại, BM25 cải tiến, hybrid và hybrid kèm reranker. Giữ cùng tập dữ liệu, bộ test và điều kiện máy; ghi riêng thời gian nạp mô hình, build chỉ mục, cold/warm query và lỗi fallback.

Ưu tiên xử lý các dạng câu hỏi đã lộ hạn chế: diễn đạt lại không trùng từ khóa, câu có số/đơn vị, nhiều điều kiện, hội thoại nối tiếp, chuyển chủ đề và so sánh hai phiên bản. Bổ sung hỏi lại khi thiếu ngành/khóa/năm áp dụng thay vì chọn một quy định bất kỳ.

Bộ kiểm tra bằng chứng xác minh đúng tài liệu, điều/khoản, phạm vi và thời điểm. Quy tắc điều kiện số cần mô hình hóa được cả ≥/>, đơn vị, ngoại lệ và điều kiện kết hợp; một con số xuất hiện trong nguồn chưa có nghĩa câu kết luận được nguồn hỗ trợ.

LLM chỉ diễn đạt sau khi đã có câu trả lời có căn cứ. Đề xuất output có cấu trúc gồm các mệnh đề và evidence_id; hậu kiểm từng mệnh đề, số liệu, URL, tên đơn vị và ngày hạn chót. Không dùng chính LLM tạo câu trả lời làm bộ đánh giá duy nhất. Nếu kiểm tra thất bại, dùng lại bản trích xuất an toàn hoặc từ chối/hỏi lại.

Ngăn chỉ dẫn trong tài liệu và câu hỏi trở thành quyền hệ thống. Không cho bước sinh trả lời tự gọi công cụ thay đổi dữ liệu hay tự quyết định học vụ. Kiểm thử tài liệu chứa “bỏ qua hướng dẫn”, liên kết độc hại và câu hỏi đánh lừa trích dẫn.

Không hiển thị confidence hiện có như “xác suất đúng”. Điểm BM25, cosine và độ phủ không cùng thang đo xác suất. Trước mắt dùng trạng thái có ý nghĩa: “Có căn cứ”, “Cần bổ sung thông tin”, “Chưa đủ căn cứ”; chỉ hiển thị xác suất sau khi có hiệu chuẩn và đánh giá độc lập.

Hybrid/reranker chỉ được bật cho người dùng khi có cải thiện có ý nghĩa thực tế, không hồi quy bộ ca an toàn và đạt ngân sách độ trễ/chi phí. Nếu không thắng, tiếp tục dùng BM25 là kết quả hợp lệ.

## 7. Chương trình C — Hội thoại, trải nghiệm và giọng nói

Giao diện trả lời ưu tiên kết luận ngắn, điều kiện áp dụng, căn cứ và lưu ý ngoại lệ; có nút mở tài liệu tại trang/đoạn. Nêu ngày tra cứu và cho người dùng chủ động đổi khi hỏi quy định cũ.

Thêm phản hồi “đúng/chưa đúng/không rõ” và lý do như sai điều khoản, sai thời điểm, thiếu thông tin hoặc lỗi nhận dạng. Phản hồi tạo ticket nội bộ, không tự ghi vào đáp án chuẩn hoặc sửa kho tri thức.

Khi thiếu thông tin, hỏi một câu làm rõ cụ thể. Khi thiếu căn cứ, chỉ chuyển tới đơn vị/liên hệ đã được nhà trường cung cấp và duyệt, không bịa số điện thoại. Người dùng được chọn có gửi kèm đoạn hội thoại cho cán bộ hay không.

Cải thiện mobile, bàn phím, focus, tương phản, cỡ chữ, thông báo lỗi và trình đọc màn hình. Cho phép hủy request, thử lại không tạo lượt trả lời trùng, xem/xóa lịch sử; giải thích giới hạn lịch sử ẩn danh khi đổi máy hay xóa dữ liệu trình duyệt.

Giọng nói: hiển thị bản nhận dạng để sửa trước khi gửi; xác định từ sai quan trọng như “không”, điểm, tín chỉ và mốc thời gian. Có dừng đọc, tốc độ đọc, phát lại, thông báo quyền microphone và fallback sang nhập chữ. Không tự ghi âm khi chưa có hành động/đồng ý của người dùng.

Xây ma trận kiểm thử Android/iOS/desktop với trình duyệt mục tiêu. Nếu STT trình duyệt không đáp ứng, thử một adapter STT máy chủ sau khi đánh giá quyền riêng tư và chi phí; không hứa chạy offline với pipeline hiện tại. Tách thời gian nhận dạng, hỏi đáp, tạo âm thanh và thời gian tới byte âm thanh đầu tiên.

Đặt chính sách TTL và phạm vi truy cập audio. Không cache công khai nội dung có dữ liệu riêng; không giữ raw audio mặc định. Nội dung gửi nhà cung cấp STT/TTS/LLM phải được mô tả rõ trong thông báo riêng tư.

## 8. Chương trình D — Danh tính, bảo mật và dữ liệu riêng tư

Giữ hỏi đáp quy chế công khai nếu không cần dữ liệu cá nhân. Thay tài khoản quản trị dùng chung bằng danh tính riêng và các vai trò: người tải tài liệu, người duyệt, quản trị hệ thống; người duyệt có quyền công bố/thu hồi theo chính sách đã chốt. Dùng giải pháp xác thực chuẩn; không tự viết hệ thống mật khẩu. SSO trường chỉ tích hợp sau khi xác nhận giao thức và quyền truy cập thực tế.

Mọi route đọc/sửa/xóa/backup phải kiểm tra quyền phía server; thêm kiểm thử truy cập chéo người dùng, nâng quyền và thu hồi phiên. Có MFA cho tài khoản đặc quyền nếu nhà cung cấp hỗ trợ, thời hạn phiên và quy trình thu hồi quyền.

Ghi audit cho tải lên, sửa metadata, duyệt, công bố, thu hồi, sửa quyền, xuất backup và khôi phục. Nhật ký gồm chủ thể, đối tượng, thời gian, hành động và kết quả; giới hạn quyền đọc/xóa, không lưu token, key hoặc nội dung hội thoại thô trong log thông thường.

Giữ và kiểm thử lại giới hạn upload, chống đường dẫn vượt thư mục, same-origin/CSRF, escape HTML, rate limit và timeout. Thêm kiểm tra định dạng thật, hạn mức trang/pixel/thời gian OCR, sandbox tiến trình xử lý và dọn tệp tạm; đánh giá quét mã độc trước khi cho tải lại tệp gốc.

Chốt mục đích thu thập, thời gian giữ lịch sử, quyền xóa và lịch hết hạn backup. Xóa ở database không đồng nghĩa xóa ngay khỏi mọi backup; phải mô tả rõ và áp dụng lại các yêu cầu xóa khi khôi phục. Tách quyền quản trị tài liệu và quyền xuất toàn bộ lịch sử; không mặc định cán bộ duyệt được đọc mọi hội thoại.

Không tuyên bố đạt chuẩn tuân thủ chỉ từ các thay đổi kỹ thuật. Chính sách nội bộ và nghĩa vụ pháp lý cần người có thẩm quyền của nhà trường rà soát.

## 9. Chương trình E — Hiệu năng, lưu trữ và vận hành

Chuyển OCR/extract/index thành job bền vững có job_id, trạng thái, tiến độ, retry có giới hạn, timeout và khả năng chạy lại không tạo dữ liệu trùng. Với một worker ban đầu, dùng bảng jobs và cơ chế claim/lease để có thể phục hồi sau restart; không mở nhiều worker trước khi kiểm chứng tính nhất quán.

Đặt cache theo khóa gồm phiên bản dữ liệu, model, cấu hình, phạm vi quyền và ngày áp dụng; không dùng cache câu trả lời cũ sau khi tài liệu thu hồi. Tách cache công khai và riêng tư. Giới hạn concurrency và hàng chờ cho LLM/TTS/OCR; có timeout tổng, circuit breaker và thông báo suy giảm dịch vụ.

Thêm request_id, log JSON, số liệu theo giai đoạn retrieval/generation/LLM/TTS/storage. Đo p50/p95/p99, tỷ lệ lỗi, fallback, từ chối, chi phí/lượt và kích thước cache. Theo dõi tỷ lệ từ chối cùng chất lượng để tránh “tăng độ chính xác bằng cách từ chối mọi câu”.

Tách liveness nhẹ khỏi readiness kiểm tra dependency cần thiết; public health không trả stack trace hoặc chi tiết nhạy cảm. Readiness không kích hoạt công việc build chỉ mục tốn kém mỗi lần probe.

Thực hiện restore drill vào môi trường trống, xác minh checksum, tài liệu, quyền owner, lịch sử, dấu xóa và revision. Đề xuất RPO ≤ 24 giờ, RTO ≤ 4 giờ cho pilot; chỉ cam kết sau khi lịch backup và diễn tập chứng minh được.

Pin phiên bản dependency bằng lock/constraints có thể tái tạo, kiểm tra lỗ hổng và giấy phép. CI chạy unit/integration/security-regression, kiểm tra giao diện và build; staging tách dữ liệu, kiểm tra migration, smoke test, backup và đường rollback trước phát hành.

Không rollback database bằng cách chép đè dữ liệu cũ. Ưu tiên migration kiểu mở rộng rồi thu hẹp, giữ tương thích với bản ứng dụng trước; mọi thay đổi production và xóa dữ liệu cần được người có quyền xác nhận.

## 10. Kế hoạch đánh giá và chỉ tiêu nghiệm thu

Mọi con số trong phần này là mục tiêu/thiết kế đề xuất, không phải kết quả đã đo. Chốt lại sau giai đoạn khảo sát baseline và khả năng máy.

Tạo tối thiểu 300 tình huống được cán bộ gán nhãn: gợi ý 120 câu trực tiếp, 60 câu diễn đạt lại, 40 hội thoại, 40 ca ngày hiệu lực/phạm vi và 40 ca thiếu căn cứ/đối kháng. Phân bố này là dự kiến, không phải số mẫu đã thu. Bổ sung riêng bộ critical gồm ngưỡng điểm, tín chỉ, thời hạn, phủ định và ngoại lệ.

Chia train/dev/test theo họ câu hỏi và tài liệu/phiên bản để tránh rò rỉ; không để một cách diễn đạt của cùng câu vào dev và cách khác vào test. Với miền dữ liệu nhỏ, dùng thêm holdout theo tài liệu và mô tả giới hạn. Giữ bộ minh họa cũ làm regression, không lấy nó làm bằng chứng duy nhất cho chất lượng thực tế.

| Chỉ tiêu | Định nghĩa và mục tiêu đề xuất | Điều kiện đo |
| --- | --- | --- |
| Tính hợp lệ của nguồn | 100% căn cứ của câu trả lời nội dung nằm trong kho đã duyệt và đúng phạm vi/ngày. | Tính trên snapshot cố định, có kiểm tra các bản thu hồi. |
| Đúng cấp điều/khoản | Mục tiêu ≥ 95% trên câu có đủ thông tin và đủ căn cứ trong test giữ kín. | Báo cả số đúng/tổng số; từ chối sai tính là không đúng. |
| Bao phủ trả lời | Báo riêng tỷ lệ câu có thể trả lời được hệ thống trả lời đúng; không được đánh đổi để làm đẹp tỷ lệ chính xác. | So sánh cùng tập và khoảng tin cậy với baseline. |
| Nhận biết thiếu căn cứ | Precision và recall từ chối mục tiêu đều ≥ 95%. | Có cả câu trả lời được và không trả lời được; không chỉ đo refusal rate. |
| An toàn số liệu | Không sai ca critical đã được duyệt; một lỗi nghiêm trọng chặn phát hành. | Không diễn giải “0 lỗi trong bộ test” thành bảo đảm không bao giờ sai. |
| Truy xuất | Theo dõi Recall@k, MRR/nDCG và đúng thời điểm; model mới phải cải thiện mà không hồi quy safety. | Cùng nhãn relevance, corpus và điều kiện tài nguyên. |
| Độ trễ hỏi bằng chữ | p95 ≤ 2 giây, không gồm STT/TTS và không bật LLM. | Khởi điểm 10 phiên đồng thời, 0,5 request/giây/phiên, 15 phút; đo thêm spike/cold start. |
| Độ trễ khi bật LLM | Mục tiêu p95 ≤ 8 giây; có fallback dưới timeout tổng đã chốt. | Ghi nhà cung cấp, model, vùng triển khai, cache và lỗi rate limit. |
| Giọng nói | Đo WER chung và lỗi từ khóa/số quan trọng; MOS mục tiêu ≥ 4/5, có phân bố và cỡ mẫu. | Tập thu âm có đồng ý, đa giọng/vùng, thiết bị và mức nhiễu; ngưỡng WER chốt sau baseline. |
| Khả dụng giao diện | SUS mục tiêu ≥ 75/100; tỷ lệ hoàn thành tác vụ mục tiêu ≥ 90%. | Pilot đề xuất 20–30 người; báo số mẫu thật, tác vụ và cách tính, không coi là đại diện toàn trường. |
| Khôi phục | RPO ≤ 24 giờ, RTO ≤ 4 giờ. | Có biên bản diễn tập với timestamp, mất dữ liệu thực tế và thời gian phục hồi. |

Các chỉ tiêu phụ thuộc nhà cung cấp phải tách khỏi thời gian xử lý nội bộ. Báo độ bất định, cỡ mẫu, corpus/model/config/commit, phần cứng và tải; không so thời gian NumPy với PyTorch để kết luận model nào nhanh hơn.

Pilot bắt đầu bằng tài liệu đã duyệt của một phạm vi hẹp và nhóm người dùng mời tham gia; gắn nhãn “thử nghiệm — không thay thế kết luận của nhà trường”. Chỉ mở rộng sau khi kiểm tra phản hồi và các gate. Dừng hoặc thu hẹp ngay khi có truy cập chéo lịch sử, nguồn chưa duyệt lọt vào câu trả lời, mất dữ liệu, hoặc sai ngưỡng/ngoại lệ có thể gây quyết định học vụ sai. Tắt riêng feature/model lỗi nếu đã khoanh vùng được; thu hồi tài liệu sai và thông báo đính chính cho người dùng bị ảnh hưởng khi có cơ chế liên hệ hợp lệ. Có người trực theo giờ đã công bố, không hứa hỗ trợ 24/7 nếu chưa có nhân sự.

## 11. Lộ trình theo cổng nghiệm thu

Ước lượng sơ bộ theo khung hai người phát triển full-time và hỗ trợ duyệt nghiệp vụ: 10–14 tuần làm việc cho pilot lõi và củng cố, chưa gồm dự phòng khoảng 20–30%. Đây là ước lượng độ tin cậy thấp, cần lập lại ở cuối G0; chưa biết quy mô văn bản và tốc độ duyệt. Mốc này loại trừ STT máy chủ, reranker nặng và nhiều instance; không cắt các điều kiện P0 để giữ lịch. Nếu chỉ làm bán thời gian hoặc thực tế chỉ có một người phát triển, cần kéo dài lịch; tham chiếu một người là khoảng 14–20 tuần trước dự phòng.

| Giai đoạn | Thời lượng dự kiến | Sản phẩm bàn giao | Cổng qua giai đoạn |
| --- | --- | --- | --- |
| G0 — Chốt baseline | 1–2 tuần | Inventory, sơ đồ luồng, kiểm tra cấu hình thật nếu có quyền, baseline test/load, danh mục văn bản ưu tiên. | Xác định nguồn và người duyệt; tái lập được bản hiện tại; có sổ rủi ro. |
| G1 — Nền tảng tin cậy | 2–3 tuần | Tách demo/thật, workflow duyệt, metadata hiệu lực/phạm vi, admin riêng, audit và restore drill. | Không truy xuất nháp/demo; kiểm thử quyền đạt; khôi phục được vào môi trường trống. |
| G2 — Chất lượng RAG | 2–3 tuần | Bộ test độc lập, sửa retrieval/hội thoại, hậu kiểm LLM, feature flags. | Đạt gate chất lượng; BM25 là fallback; mọi model mới có báo cáo đối chứng. |
| G3 — UX và vận hành | 2–3 tuần | Trích dẫn tới trang, feedback, mobile/accessibility, jobs tài liệu, telemetry, CI/staging. | Luồng sinh viên/quản trị chạy end-to-end; lỗi job không làm hỏng snapshot đang dùng. |
| G4 — Pilot và đo thật | 2–3 tuần | Pilot giới hạn, đo SUS/MOS/WER/latency phù hợp phạm vi, sửa lỗi ưu tiên. | Không còn lỗi critical; có người trực và runbook; chỉ tiêu đạt hoặc có quyết định thu hẹp phạm vi. |
| G5 — Củng cố và bàn giao | 1–2 tuần | Hardening, tài liệu vận hành, kế hoạch cập nhật văn bản, báo cáo nghiệm thu. | Chấp thuận bởi người quyết định; phát hành có xác nhận riêng; có rollback đã kiểm tra. |

G1 phải có tập văn bản đã duyệt trước khi chốt test thực của G2. Luồng A tập trung dữ liệu/RAG và luồng B tập trung auth/UI/CI/vận hành. G3 có thể khởi động phần độc lập trong G1 và chạy song song G2; không cộng thẳng mọi thời lượng thành lịch nối tiếp hoặc tính cùng một người vào hai việc full-time. Kế hoạch lịch tham chiếu: G0 tuần 1–2; G1 tuần 3–5; G2 tuần 6–8; G3 phần độc lập từ tuần 4, tích hợp xong tuần 8–9; G4 tuần 9–12; G5 tuần 12–14. Ngày bắt đầu thực tế và năng lực từng người được chốt sau G0.

## 12. Backlog triển khai ưu tiên

Mỗi dòng là một nhóm việc cần tách thành ticket 1–3 ngày khi bắt đầu. Cột phụ thuộc là quan hệ kỹ thuật/nghiệp vụ, không phải lịch cam kết.

| Mã | Ưu tiên | Công việc | Phụ thuộc | Tiêu chí hoàn thành cốt lõi |
| --- | --- | --- | --- | --- |
| HV-01 | P0 | Baseline và bản phát hành tái tạo được | Không | Có commit/config/corpus và báo cáo test thực tế. |
| HV-02 | P0 | Tách corpus demo/official | HV-01 | Official không sinh chỉ mục/gợi ý từ dữ liệu demo. |
| HV-03 | P0 | Chuẩn metadata và vòng đời văn bản | HV-02 | Nháp không công khai; công bố có người duyệt. |
| HV-04 | P0 | Ngày hiệu lực, phạm vi, thay thế một phần | HV-03 | Test đúng trước/sau mốc ngày và khác đối tượng. |
| HV-05 | P0 | Danh tính quản trị và quyền server-side | HV-01 | Tài khoản bị thu hồi không đọc/ghi/backup vượt quyền. |
| HV-06 | P0 | Snapshot chỉ mục, công bố/rollback an toàn | HV-03,04 | Job lỗi không thay chỉ mục đang phục vụ. |
| HV-07 | P0 | Bộ đánh giá độc lập và test critical | HV-03,04 | Có nhãn người duyệt, test giữ kín, không rò rỉ paraphrase. |
| HV-08 | P0 | Evidence gate và hậu kiểm LLM | HV-07 | Rewrite thêm số/ngày/điều kiện sai bị loại bỏ. |
| HV-09 | P0 | Lưu trữ thật và diễn tập restore | HV-01,05 | Cache trống vẫn phục hồi đúng quyền/lịch sử/tài liệu. |
| HV-10 | P0 | Audit, retention và thông báo riêng tư | HV-03,05 | Truy vết được công bố; log không chứa bí mật. |
| HV-11 | P1 | OCR đối chiếu và review bảng/số liệu | HV-03 | Người duyệt xem được nguồn và chỗ cần kiểm tra. |
| HV-12 | P1 | Hỏi lại và hội thoại chuyển chủ đề | HV-07 | Không mượn căn cứ cũ cho chủ đề mới thiếu nguồn. |
| HV-13 | P1 | Trích dẫn trang/đoạn và UX áp dụng | HV-04,06 | Người dùng mở đúng nguồn, thấy ngày/phạm vi. |
| HV-14 | P1 | Feedback và hàng xử lý cán bộ | HV-05,10,13 | Phản hồi được phân loại, không tự thành tri thức. |
| HV-15 | P1 | Jobs tài liệu bền vững và retry | HV-06,09 | Restart tiếp tục/khôi phục job, không nhân đôi công bố. |
| HV-16 | P1 | Metrics, health, timeout và hạn mức | HV-01 | Có dashboard vận hành và cảnh báo kiểm chứng được. |
| HV-17 | P1 | CI, staging, dependency lock và migration | HV-01,09 | Bản fail gate không được phát hành; có rehearsal rollback. |
| HV-18 | P1 | Mobile, accessibility và voice fallback | HV-13 | Luồng chính chạy bằng bàn phím và nhập chữ khi mic lỗi. |
| HV-19 | P1 | Đo thực nghiệm và pilot | HV-07,09,13,16,17 | Có dữ liệu đồng ý tham gia và báo cáo không bịa số. |
| HV-20 | P2 | Hybrid/reranker có đối chứng | HV-07,16 | Chỉ bật khi thắng baseline và đạt chi phí/độ trễ. |
| HV-21 | P2 | STT máy chủ, tối ưu âm thanh | HV-18,19 | Chứng minh cần thiết, có privacy review và ngân sách. |
| HV-22 | P2 | Nhiều instance và giới hạn dùng chung | HV-15,16,17 | Đạt load test, nhất quán snapshot và owner isolation. |

Ví dụ tiêu chí kiểm thử có thể chuyển thành test:

- Cho một tài liệu ở trạng thái nháp; khi sinh viên hỏi nội dung chỉ có trong tài liệu đó; hệ thống không trích tài liệu và phải thông báo thiếu căn cứ.
- Cho hai quy định có thời gian áp dụng khác nhau; khi hỏi cùng một câu trước và sau mốc thay thế; nguồn trả về đúng với ngày tra cứu và đối tượng.
- Cho LLM đổi “từ 2,5 trở lên” thành “trên 2,5”; khi hậu kiểm; không trả bản rewrite đó và giữ lại câu trích xuất an toàn.
- Cho người dùng A có hội thoại riêng; khi B đọc/xóa theo ID hội thoại của A; API từ chối và không để lộ nội dung.
- Cho job lập chỉ mục lỗi giữa chừng; khi vẫn có lượt hỏi; lượt hỏi dùng snapshot cũ nhất quán, không dùng chỉ mục nửa chừng.
- Cho bản backup và các yêu cầu xóa phát sinh sau backup; khi phục hồi; các tombstone/chính sách xóa được áp dụng trước khi mở dịch vụ cho người dùng.

## 13. Nhân sự, chi phí và quản lý rủi ro

Driver: người phát triển HocVu AI, chịu trách nhiệm backlog và kết quả kỹ thuật. Approver: một người do nhà trường/đồ án chỉ định, quyết định phạm vi và cho phép pilot. Contributor: cán bộ quy chế, người kiểm thử/UX và người vận hành. Informed: giảng viên hướng dẫn, đơn vị liên quan và nhóm người dùng pilot. Một người có thể kiêm vai, nhưng nếu chưa có người duyệt độc lập phải ghi rõ giới hạn và chỉ giữ ở chế độ demo.

Chưa đủ thông tin để dự toán tiền theo tháng. Không chốt cấu hình RAM hay mua GPU chỉ dựa vào thí nghiệm NumPy trước đó. G0 phải đo peak RAM/CPU khi nạp model, OCR và tải đồng thời, rồi mới chọn máy.

Công thức ngân sách: chi phí máy chạy + database + dung lượng/đọc ghi object storage + lưu/khôi phục backup + LLM theo token + STT theo phút + TTS theo ký tự/phút + giám sát. Lập ba kịch bản tải thấp, dự kiến và cao dựa trên số lượt thật/giả định được ghi rõ; đặt trần chi phí ngày/tháng, cảnh báo và khả năng tắt AI về BM25. Phí nhân công và thời gian duyệt văn bản tính riêng.

| Rủi ro | Ảnh hưởng | Biện pháp và người chịu trách nhiệm |
| --- | --- | --- |
| Thiếu văn bản/quyền dùng hoặc người duyệt | Không đủ điều kiện ra dùng thật | Approver thu hẹp phạm vi; không thay bằng dữ liệu tự bịa. |
| OCR sai số/ngoại lệ hoặc văn bản sửa đổi một phần | Tư vấn sai quy chế | Cán bộ đối chiếu, test critical, thu hồi nguồn và rollback snapshot. |
| Tối ưu vào test minh họa | Điểm đẹp nhưng không dùng được | Developer giữ test độc lập, phân nhóm lỗi và kiểm tra holdout. |
| LLM thêm thông tin hoặc bị prompt injection | Sai câu trả lời dù trích dẫn có thật | Hậu kiểm, evidence IDs, fallback và feature flag tắt model. |
| Mất dữ liệu hoặc restore làm sống lại dữ liệu đã xóa | Mất riêng tư/tính toàn vẹn | Operator restore drill, tombstone, retention và quyền backup riêng. |
| Nhóm nhỏ, kiêm nhiệm và phụ thuộc người duyệt | Trễ hoặc bỏ kiểm thử | Cắt P2 trước; giới hạn việc đang làm, bố trí review chéo và đặt lịch duyệt cố định. |
| Dịch vụ giọng nói/LLM lỗi hoặc tăng chi phí | Gián đoạn/tràn ngân sách | Timeout, hạn mức, fallback chữ/BM25 và cảnh báo chi phí. |

## 14. Công việc khởi động và quyết định cần chốt

Trong 10 ngày làm việc đầu tiên, ưu tiên HV-01 và thiết kế HV-02/HV-03/HV-07: chụp baseline, kiểm tra môi trường có quyền truy cập, gom danh mục văn bản, thống nhất metadata, xác định người duyệt và lấy tập câu hỏi đại diện. Sau đó bàn giao báo cáo khoảng cách hiện trạng, bộ test khởi điểm và backlog chi tiết của G1.

Phân công đề xuất cho 10 ngày đầu:

- Backend/RAG: tái lập baseline, lập bản đồ corpus/chunk/index, phân loại lỗi và thiết kế tách official/demo; lập thử nhãn cho 20–30 tình huống cùng cán bộ.
- Frontend/full-stack: đi lại các luồng hỏi/đọc nguồn/quản trị, kiểm tra accessibility, kiểm kê auth và lưu trữ; dựng CI/staging tối thiểu và sơ đồ UX duyệt văn bản.
- Cán bộ nghiệp vụ: chốt nguồn, phạm vi, phiên bản và các ca critical; duyệt nhãn mẫu trước khi nhân rộng bộ test.
- Người phụ trách pilot: chốt nhóm thử nghiệm, thông báo riêng tư, đầu mối xử lý sự cố và hạn mức chi phí; duyệt phạm vi G1.

Nếu mục tiêu chỉ là hoàn thiện đồ án, bản tối thiểu nên gồm tách demo/thật, bộ test độc lập, hậu kiểm trả lời, luồng duyệt, đo thật các chỉ tiêu đã nêu và cập nhật báo cáo. Nếu mục tiêu là phục vụ sinh viên thật, phải thêm danh tính quản trị riêng, quyền server-side, lưu trữ/restore, privacy, giám sát và người trực; không gắn nhãn “production-ready” khi chưa kiểm chứng.

Các quyết định còn mở: số thành viên/thời gian thực tế của nhóm nhỏ; cán bộ duyệt; phạm vi văn bản/đối tượng áp dụng; tải mục tiêu; chính sách lưu giữ; ngân sách nhà cung cấp; nền tảng danh tính được trường cho phép. Hướng triển khai thử đã được người dùng xác nhận. Không cần giải quyết tất cả trước G0, nhưng phải chốt các mục ảnh hưởng trước khi bước sang giai đoạn liên quan.

Kế hoạch này chưa cho phép sửa mã, di chuyển dữ liệu hay phát hành production. Khi bắt đầu triển khai, thực hiện từng nhóm việc trong dự án hiện có, có nhánh/checkpoint, kiểm thử và nghiệm thu.

Rà soát tài liệu sau mỗi cổng nghiệm thu và sau pilot; cập nhật version/changelog thay vì giữ nguyên lịch trình khi dữ liệu thực tế thay đổi.

## Nguồn và nhật ký phiên bản

[S1] Hướng dẫn kiến trúc, auth, cấu hình và dữ liệu trong kho: https://github.com/MasterStupid/hocvu/blob/3f35189/replit.md

[S2] Điều phối, build corpus, ngày hiệu lực, bằng chứng và LLM: https://github.com/MasterStupid/hocvu/blob/3f35189/core/engine.py

[S3] BM25, hybrid và cơ chế chỉ mục: https://github.com/MasterStupid/hocvu/blob/3f35189/core/searcher.py

[S4] Gọi LLM và rewrite: https://github.com/MasterStupid/hocvu/blob/3f35189/core/llm.py

[S5] API, xác thực, giới hạn truy cập, quản trị và health: https://github.com/MasterStupid/hocvu/blob/3f35189/server/app.py

[S6] Lưu trữ, backup, import và kiểm chứng triển khai: https://github.com/MasterStupid/hocvu/blob/3f35189/docs/persistent-storage.md

[S7] TTS, tạo và cache âm thanh: https://github.com/MasterStupid/hocvu/blob/3f35189/core/voice.py

Nguồn kết quả minh họa: bản báo cáo HocVu AI v3 đã bàn giao trong cuộc trò chuyện; exp_bm25.json và exp_hybrid.json của đợt tái lập trước. Không sử dụng chúng để suy ra kết quả trên tài liệu chính thức hay cấu hình production.

Changelog 1.0 — 09/11/2026: Lập kế hoạch ban đầu từ mã nguồn 3f35189; điều chỉnh theo lựa chọn “nhóm nhỏ triển khai thử”; tách rõ hiện trạng, đề xuất và tiêu chí chưa đo.
