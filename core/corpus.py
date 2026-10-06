import json
import random
from typing import Dict, Any, List, Optional
from datetime import datetime
from .models import Regulation, Article, Clause, TestQuestion

# Internal helper dict structure for definition
_MOCK_DATA = [
    {
        "rid": "QD-DTDC-HPU-2026",
        "title": "Quy định Đào tạo Đại cương",
        "category": "Đào tạo",
        "version": "2026",
        "valid_from": "2026-09-01",
        "valid_until": None,
        "issuer": "Đại học Hải Phòng",
        "articles": [
            {
                "aid": "Điều 1",
                "heading": "Phạm vi và đối tượng áp dụng",
                "clauses": [
                    {"cid": "1", "content": "Quy định này áp dụng cho toàn bộ sinh viên hệ đại học chính quy nhập học từ năm 2026 trở đi tại Đại học Hải Phòng (HPU).", "qa": []},
                    {"cid": "2", "content": "Khối kiến thức giáo dục đại cương bao gồm 45 tín chỉ, trong đó có 30 tín chỉ bắt buộc và 15 tín chỉ tự chọn.", "qa": [{"q": "Sinh viên cần bao nhiêu tín chỉ đại cương?", "category": "factual", "difficulty": "easy"}]}
                ]
            },
            {
                "aid": "Điều 2",
                "heading": "Điều kiện học ngoại ngữ đại cương",
                "clauses": [
                    {"cid": "1", "content": "Sinh viên phải đạt tối thiểu 450 điểm TOEIC nội bộ để được đăng ký các học phần tiếng Anh chuyên ngành.", "qa": [{"q": "Điểm TOEIC tối thiểu để học tiếng Anh chuyên ngành là bao nhiêu?", "category": "factual", "difficulty": "easy"}]},
                    {"cid": "2", "content": "Sinh viên có chứng chỉ IELTS từ 5.5 trở lên được miễn toàn bộ học phần tiếng Anh đại cương và được quy đổi điểm 10.", "qa": [{"q": "IELTS 5.5 được quy đổi như thế nào?", "category": "conditional", "difficulty": "medium"}]}
                ]
            },
            {
                "aid": "Điều 3",
                "heading": "Quy định về điểm danh và chuyên cần",
                "clauses": [
                    {"cid": "1", "content": "Sinh viên vắng mặt quá 25% tổng số tiết học của học phần sẽ bị cấm thi cuối kỳ.", "qa": [{"q": "Nghỉ học bao nhiêu phần trăm thì bị cấm thi?", "category": "factual", "difficulty": "easy"}]},
                    {"cid": "2", "content": "Điểm chuyên cần chiếm 10% tổng điểm học phần, được đánh giá qua mức độ tham gia bài tập trên lớp và thảo luận.", "qa": []},
                    {"cid": "3", "content": "Việc điểm danh hộ dưới bất kỳ hình thức nào sẽ bị trừ toàn bộ điểm chuyên cần của học kỳ đó.", "qa": [{"q": "Điểm danh hộ bị xử lý ra sao?", "category": "factual", "difficulty": "medium"}]}
                ]
            },
            {
                "aid": "Điều 4",
                "heading": "Thi lại và học lại",
                "clauses": [
                    {"cid": "1", "content": "Sinh viên có điểm học phần dưới 4.0 (thang điểm 10) phải đăng ký học lại học phần đó.", "qa": [{"q": "Điểm dưới bao nhiêu thì phải học lại?", "category": "factual", "difficulty": "easy"}]},
                    {"cid": "2", "content": "Không tổ chức thi lại cho các học phần đại cương từ năm 2026. Sinh viên trượt phải học lại toàn bộ.", "qa": [{"q": "Quy định thi lại từ năm 2026 thế nào?", "category": "comparison", "difficulty": "hard"}]}
                ]
            },
            {
                "aid": "Điều 5",
                "heading": "Bảo lưu kết quả học tập",
                "clauses": [
                    {"cid": "1", "content": "Thời gian bảo lưu tối đa là 4 học kỳ chính. Hết thời hạn này, sinh viên phải quay lại học hoặc bị buộc thôi học.", "qa": [{"q": "Sinh viên được bảo lưu tối đa bao nhiêu học kỳ?", "category": "factual", "difficulty": "medium"}]},
                    {"cid": "2", "content": "Điều kiện bảo lưu: Sinh viên không bị kỷ luật từ mức cảnh cáo trở lên và đã hoàn thành ít nhất 1 học kỳ tại trường.", "qa": [{"q": "Tân sinh viên chưa học xong kỳ 1 có được bảo lưu không?", "category": "conditional", "difficulty": "hard"}]}
                ]
            },
            {
                "aid": "Điều 6",
                "heading": "Học cùng lúc hai chương trình (Song ngành)",
                "clauses": [
                    {"cid": "1", "content": "Sinh viên được đăng ký học song ngành khi điểm trung bình tích lũy đạt từ 2.8 trở lên và tín chỉ tích lũy đạt từ 30 tín chỉ.", "qa": [{"q": "Điều kiện để học song ngành là gì?", "category": "factual", "difficulty": "medium"}]},
                    {"cid": "2", "content": "Sinh viên học song ngành đóng học phí theo số tín chỉ thực tế đăng ký cộng thêm phụ phí quản lý 15%.", "qa": []}
                ]
            },
            {
                "aid": "Điều 7",
                "heading": "Cảnh báo học vụ",
                "clauses": [
                    {"cid": "1", "content": "Cảnh báo học vụ mức 1 áp dụng khi điểm trung bình học kỳ dưới 1.2 đối với năm nhất, hoặc dưới 1.4 đối với các năm tiếp theo.", "qa": [{"q": "Điểm trung bình học kỳ 1.3 của năm 2 có bị cảnh báo học vụ không?", "category": "conditional", "difficulty": "medium"}]},
                    {"cid": "2", "content": "Sinh viên bị cảnh báo học vụ 3 lần liên tiếp sẽ bị buộc thôi học.", "qa": [{"q": "Bị cảnh báo học vụ bao nhiêu lần thì buộc thôi học?", "category": "factual", "difficulty": "easy"}]}
                ]
            },
            {
                "aid": "Điều 8",
                "heading": "Điều khoản thi hành",
                "clauses": [
                    {"cid": "1", "content": "Quy định này có hiệu lực từ ngày 01/09/2026, thay thế cho Quy định QD-DTDC-HPU-2024.", "qa": []},
                    {"cid": "2", "content": "Phòng Đào tạo chịu trách nhiệm hướng dẫn và giải quyết các vướng mắc trong quá trình thực hiện.", "qa": []}
                ]
            }
        ]
    },
    {
        "rid": "QD-TTTN-HPU-2026",
        "title": "Quy định Thực tập và Tốt nghiệp",
        "category": "Tốt nghiệp",
        "version": "2026",
        "valid_from": "2026-01-01",
        "valid_until": None,
        "issuer": "Đại học Hải Phòng",
        "articles": [
            {
                "aid": "Điều 1",
                "heading": "Điều kiện đi thực tập",
                "clauses": [
                    {"cid": "1", "content": "Sinh viên được phép đăng ký thực tập doanh nghiệp khi đã tích lũy tối thiểu 110 tín chỉ đối với hệ cử nhân và 135 tín chỉ đối với hệ kỹ sư.", "qa": [{"q": "Sinh viên hệ kỹ sư cần bao nhiêu tín chỉ để đi thực tập?", "category": "factual", "difficulty": "easy"}]},
                    {"cid": "2", "content": "Sinh viên không được nợ quá 2 học phần bắt buộc thuộc khối kiến thức chuyên ngành tại thời điểm đăng ký.", "qa": [{"q": "Nợ 3 môn chuyên ngành có được đi thực tập không?", "category": "conditional", "difficulty": "medium"}]}
                ]
            },
            {
                "aid": "Điều 2",
                "heading": "Thời gian và khối lượng thực tập",
                "clauses": [
                    {"cid": "1", "content": "Kỳ thực tập kéo dài tối thiểu 12 tuần và tối đa 20 tuần tại các doanh nghiệp đối tác hoặc cơ sở được trường chấp thuận.", "qa": [{"q": "Thời gian thực tập tối thiểu là bao lâu?", "category": "factual", "difficulty": "easy"}]},
                    {"cid": "2", "content": "Khối lượng học phần thực tập tương đương 6 tín chỉ. Đánh giá dựa trên báo cáo thực tập (40%) và đánh giá của doanh nghiệp (60%).", "qa": [{"q": "Điểm thực tập được tính như thế nào?", "category": "factual", "difficulty": "medium"}]}
                ]
            },
            {
                "aid": "Điều 3",
                "heading": "Đồ án/Khóa luận tốt nghiệp",
                "clauses": [
                    {"cid": "1", "content": "Đồ án tốt nghiệp tương đương 10 tín chỉ (hệ cử nhân) và 14 tín chỉ (hệ kỹ sư).", "qa": [{"q": "Đồ án tốt nghiệp kỹ sư mấy tín chỉ?", "category": "factual", "difficulty": "easy"}]},
                    {"cid": "2", "content": "Điều kiện làm đồ án: Điểm trung bình tích lũy từ 2.5 trở lên, không bị kỷ luật. Các sinh viên không đủ điều kiện sẽ học các học phần thay thế tốt nghiệp.", "qa": [{"q": "Điểm tích lũy 2.4 có được làm đồ án tốt nghiệp không?", "category": "conditional", "difficulty": "medium"}]}
                ]
            },
            {
                "aid": "Điều 4",
                "heading": "Điều kiện xét tốt nghiệp",
                "clauses": [
                    {"cid": "1", "content": "Tích lũy đủ số tín chỉ quy định của chương trình đào tạo (130 tín chỉ cử nhân, 160 tín chỉ kỹ sư).", "qa": [{"q": "Số tín chỉ tốt nghiệp hệ cử nhân là bao nhiêu?", "category": "factual", "difficulty": "easy"}]},
                    {"cid": "2", "content": "Có chứng chỉ Tiếng Anh tương đương bậc 3/6 Khung năng lực ngoại ngữ Việt Nam và chứng chỉ Tin học cơ bản.", "qa": [{"q": "Cần chứng chỉ ngoại ngữ gì để tốt nghiệp?", "category": "factual", "difficulty": "easy"}]},
                    {"cid": "3", "content": "Có chứng chỉ Giáo dục quốc phòng - an ninh và chứng chỉ Giáo dục thể chất.", "qa": []}
                ]
            },
            {
                "aid": "Điều 5",
                "heading": "Xếp loại hạng tốt nghiệp",
                "clauses": [
                    {"cid": "1", "content": "Xuất sắc: Điểm tích lũy từ 3.60 đến 4.00. Giỏi: Từ 3.20 đến 3.59. Khá: Từ 2.50 đến 3.19. Trung bình: Từ 2.00 đến 2.49.", "qa": [{"q": "Điểm 3.3 được xếp loại bằng gì?", "category": "factual", "difficulty": "medium"}]},
                    {"cid": "2", "content": "Hạng tốt nghiệp sẽ bị giảm một bậc nếu sinh viên có khối lượng học phần thi lại vượt quá 10% tổng số tín chỉ hoặc từng bị kỷ luật mức cảnh cáo.", "qa": [{"q": "Học lại 15% tín chỉ có ảnh hưởng đến bằng tốt nghiệp không?", "category": "conditional", "difficulty": "hard"}]}
                ]
            },
            {
                "aid": "Điều 6",
                "heading": "Thời hạn cấp bằng",
                "clauses": [
                    {"cid": "1", "content": "Bằng tốt nghiệp và bảng điểm chính thức sẽ được cấp trong vòng 30 ngày làm việc kể từ ngày có quyết định công nhận tốt nghiệp.", "qa": [{"q": "Sau khi có quyết định tốt nghiệp bao lâu thì nhận được bằng?", "category": "factual", "difficulty": "easy"}]}
                ]
            }
        ]
    },
    {
        "rid": "QD-HBHT-HPU-2026",
        "title": "Quy định Học bổng và Hỗ trợ tài chính",
        "category": "Tài chính",
        "version": "2026",
        "valid_from": "2026-08-15",
        "valid_until": None,
        "issuer": "Đại học Hải Phòng",
        "articles": [
            {
                "aid": "Điều 1",
                "heading": "Học bổng khuyến khích học tập (HBKKHT)",
                "clauses": [
                    {"cid": "1", "content": "HBKKHT được xét theo từng học kỳ dựa trên kết quả học tập và điểm rèn luyện của học kỳ trước đó.", "qa": []},
                    {"cid": "2", "content": "Quỹ HBKKHT trích từ 8% tổng nguồn thu học phí hệ chính quy của trường.", "qa": [{"q": "Trường trích bao nhiêu phần trăm học phí cho quỹ học bổng?", "category": "factual", "difficulty": "medium"}]}
                ]
            },
            {
                "aid": "Điều 2",
                "heading": "Tiêu chuẩn và mức xét HBKKHT",
                "clauses": [
                    {"cid": "1", "content": "Loại Xuất sắc (Thưởng 150% học phí): Điểm học tập >= 3.6 và Điểm rèn luyện >= 90.", "qa": [{"q": "Học bổng xuất sắc thưởng bao nhiêu tiền?", "category": "factual", "difficulty": "easy"}]},
                    {"cid": "2", "content": "Loại Giỏi (Thưởng 120% học phí): Điểm học tập từ 3.2 đến 3.59 và Điểm rèn luyện >= 80.", "qa": [{"q": "Điểm học tập 3.4, điểm rèn luyện 85 thì được học bổng loại gì?", "category": "conditional", "difficulty": "medium"}]},
                    {"cid": "3", "content": "Loại Khá (Thưởng 100% học phí): Điểm học tập từ 2.5 đến 3.19 và Điểm rèn luyện >= 70.", "qa": []},
                    {"cid": "4", "content": "Chỉ xét sinh viên đăng ký tối thiểu 15 tín chỉ trong học kỳ xét (không tính học kỳ cuối).", "qa": [{"q": "Đăng ký 12 tín chỉ trong học kỳ có được xét học bổng không?", "category": "conditional", "difficulty": "hard"}]}
                ]
            },
            {
                "aid": "Điều 3",
                "heading": "Hỗ trợ sinh viên khó khăn",
                "clauses": [
                    {"cid": "1", "content": "Sinh viên thuộc hộ nghèo theo quy định của Nhà nước được giảm 50% học phí và nhận trợ cấp sinh hoạt 500,000 VNĐ/tháng.", "qa": [{"q": "Sinh viên hộ nghèo được hỗ trợ sinh hoạt phí bao nhiêu?", "category": "factual", "difficulty": "easy"}]},
                    {"cid": "2", "content": "Sinh viên khuyết tật nặng được miễn 100% học phí toàn khóa học.", "qa": [{"q": "Chính sách học phí cho sinh viên khuyết tật nặng thế nào?", "category": "factual", "difficulty": "easy"}]}
                ]
            },
            {
                "aid": "Điều 4",
                "heading": "Quỹ học bổng doanh nghiệp",
                "clauses": [
                    {"cid": "1", "content": "Mỗi năm học, HPU cung cấp ít nhất 50 suất học bổng doanh nghiệp trị giá 10 triệu đồng/suất cho sinh viên ngành kỹ thuật và công nghệ.", "qa": [{"q": "Trị giá học bổng doanh nghiệp là bao nhiêu?", "category": "factual", "difficulty": "medium"}]}
                ]
            },
            {
                "aid": "Điều 5",
                "heading": "Thủ tục nhận học bổng",
                "clauses": [
                    {"cid": "1", "content": "Tiền học bổng và trợ cấp sẽ được chuyển khoản trực tiếp vào tài khoản ngân hàng liên kết của sinh viên vào tuần thứ 6 của học kỳ.", "qa": [{"q": "Học bổng được phát vào thời gian nào trong học kỳ?", "category": "factual", "difficulty": "easy"}]}
                ]
            }
        ]
    },
    {
        "rid": "QD-RLSV-HPU-2026",
        "title": "Quy định Rèn luyện Sinh viên",
        "category": "Đánh giá",
        "version": "2026",
        "valid_from": "2026-08-01",
        "valid_until": None,
        "issuer": "Đại học Hải Phòng",
        "articles": [
            {
                "aid": "Điều 1",
                "heading": "Mục đích đánh giá rèn luyện",
                "clauses": [
                    {"cid": "1", "content": "Đánh giá điểm rèn luyện (ĐRL) nhằm đo lường ý thức kỷ luật, tinh thần tham gia phong trào, và thái độ học tập của sinh viên.", "qa": []}
                ]
            },
            {
                "aid": "Điều 2",
                "heading": "Thang điểm và tiêu chí",
                "clauses": [
                    {"cid": "1", "content": "Tổng điểm rèn luyện tối đa là 100 điểm, chia thành 4 nhóm tiêu chí chính.", "qa": [{"q": "Điểm rèn luyện tối đa là bao nhiêu?", "category": "factual", "difficulty": "easy"}]},
                    {"cid": "2", "content": "Ý thức học tập và chuyên cần: Tối đa 30 điểm. Cộng 3 điểm nếu có chứng chỉ ngoại ngữ vượt chuẩn.", "qa": []},
                    {"cid": "3", "content": "Chấp hành nội quy, quy chế: Tối đa 25 điểm. Trừ 5 điểm/lần nếu vi phạm quy định về trang phục.", "qa": [{"q": "Vi phạm quy định trang phục bị trừ bao nhiêu điểm rèn luyện?", "category": "factual", "difficulty": "medium"}]},
                    {"cid": "4", "content": "Tham gia hoạt động Đoàn - Hội và tình nguyện: Tối đa 25 điểm. Sinh viên hiến máu nhân đạo được cộng 10 điểm/lần.", "qa": [{"q": "Hiến máu nhân đạo được cộng mấy điểm?", "category": "factual", "difficulty": "easy"}]},
                    {"cid": "5", "content": "Phẩm chất công dân và thành tích đặc biệt: Tối đa 20 điểm.", "qa": []}
                ]
            },
            {
                "aid": "Điều 3",
                "heading": "Xếp loại điểm rèn luyện",
                "clauses": [
                    {"cid": "1", "content": "Từ 90-100 điểm: Xuất sắc; Từ 80-89 điểm: Tốt; Từ 65-79 điểm: Khá; Từ 50-64 điểm: Trung bình; Dưới 50 điểm: Yếu.", "qa": [{"q": "75 điểm rèn luyện xếp loại gì?", "category": "factual", "difficulty": "medium"}]}
                ]
            },
            {
                "aid": "Điều 4",
                "heading": "Xử lý kết quả rèn luyện yếu",
                "clauses": [
                    {"cid": "1", "content": "Sinh viên có ĐRL xếp loại Yếu trong 2 học kỳ liên tiếp sẽ bị tạm đình chỉ học tập 1 học kỳ.", "qa": [{"q": "Xếp loại rèn luyện Yếu 2 kỳ liên tiếp bị sao?", "category": "factual", "difficulty": "easy"}]},
                    {"cid": "2", "content": "Điểm rèn luyện toàn khóa dưới Trung bình sẽ không được xét tốt nghiệp.", "qa": [{"q": "Điểm rèn luyện toàn khoá Yếu có được ra trường không?", "category": "conditional", "difficulty": "medium"}]}
                ]
            },
            {
                "aid": "Điều 5",
                "heading": "Khen thưởng",
                "clauses": [
                    {"cid": "1", "content": "Sinh viên xếp loại rèn luyện Xuất sắc và Tốt được cộng điểm ưu tiên khi đăng ký ở Ký túc xá.", "qa": []}
                ]
            },
            {
                "aid": "Điều 6",
                "heading": "Kỷ luật sinh viên",
                "clauses": [
                    {"cid": "1", "content": "Khiển trách: Trừ 15 ĐRL. Cảnh cáo: Trừ 30 ĐRL. Đình chỉ có thời hạn: Xếp loại Kém.", "qa": [{"q": "Bị khiển trách trừ bao nhiêu điểm rèn luyện?", "category": "factual", "difficulty": "easy"}]},
                    {"cid": "2", "content": "Sinh viên gian lận trong thi cử (mang tài liệu, quay cóp) bị đình chỉ học tập 1 năm và nhận 0 ĐRL cho học kỳ đó.", "qa": [{"q": "Gian lận thi cử bị kỷ luật như thế nào?", "category": "factual", "difficulty": "medium"}]}
                ]
            },
            {
                "aid": "Điều 7",
                "heading": "Quy trình đánh giá",
                "clauses": [
                    {"cid": "1", "content": "Quy trình gồm 3 bước: Cá nhân sinh viên tự đánh giá -> Tập thể lớp đánh giá -> Hội đồng khoa duyệt kết quả.", "qa": [{"q": "Quy trình đánh giá điểm rèn luyện gồm mấy bước?", "category": "factual", "difficulty": "easy"}]}
                ]
            }
        ]
    },
    {
        "rid": "QD-DTDC-HPU-2024",
        "title": "Quy định Đào tạo Đại cương (Phiên bản cũ)",
        "category": "Đào tạo",
        "version": "2024",
        "valid_from": "2024-09-01",
        "valid_until": "2026-08-31",
        "issuer": "Đại học Hải Phòng",
        "articles": [
            {
                "aid": "Điều 1",
                "heading": "Khối lượng kiến thức",
                "clauses": [
                    {"cid": "1", "content": "Khối kiến thức đại cương bắt buộc là 35 tín chỉ, không có tín chỉ tự chọn cho khối đại cương.", "qa": [{"q": "Quy định cũ sinh viên cần bao nhiêu tín chỉ đại cương?", "category": "comparison", "difficulty": "hard"}]}
                ]
            },
            {
                "aid": "Điều 2",
                "heading": "Ngoại ngữ",
                "clauses": [
                    {"cid": "1", "content": "Yêu cầu TOEIC nội bộ tối thiểu là 350 điểm để được học tiếp ngoại ngữ chuyên ngành.", "qa": [{"q": "Năm 2024, TOEIC tối thiểu là bao nhiêu?", "category": "factual", "difficulty": "easy"}]}
                ]
            },
            {
                "aid": "Điều 3",
                "heading": "Thi lại",
                "clauses": [
                    {"cid": "1", "content": "Sinh viên được thi lại 1 lần nếu điểm tổng kết học phần dưới 4.0. Điểm thi lại tối đa chỉ được ghi nhận là 5.5.", "qa": [{"q": "Quy định cũ có cho phép thi lại không?", "category": "comparison", "difficulty": "medium"}]}
                ]
            },
            {
                "aid": "Điều 4",
                "heading": "Bảo lưu",
                "clauses": [
                    {"cid": "1", "content": "Được phép bảo lưu tối đa 2 học kỳ chính vì lý do cá nhân.", "qa": []}
                ]
            },
            {
                "aid": "Điều 5",
                "heading": "Điều khoản thay thế",
                "clauses": [
                    {"cid": "1", "content": "Quy định này hết hiệu lực vào ngày 31/08/2026 và được thay thế bằng QD-DTDC-HPU-2026.", "qa": []}
                ]
            }
        ]
    }
]

_OUT_OF_SCOPE_QUESTIONS = [
    {"q": "Trường có nhà thi đấu bơi lội không?", "category": "out_of_scope", "difficulty": "easy", "should_refuse": True},
    {"q": "Quy định gửi xe ở cơ sở 2 thế nào?", "category": "out_of_scope", "difficulty": "easy", "should_refuse": True},
    {"q": "Làm sao để đăng ký vào câu lạc bộ guitar trường?", "category": "out_of_scope", "difficulty": "medium", "should_refuse": True},
    {"q": "Giờ giới nghiêm của ký túc xá nam là mấy giờ?", "category": "out_of_scope", "difficulty": "medium", "should_refuse": True},
    {"q": "Cơm ở căng tin trường số 1 giá bao nhiêu tiền một suất?", "category": "out_of_scope", "difficulty": "easy", "should_refuse": True},
    {"q": "Bảo vệ trường có cho phép mang chó mèo vào lớp học không?", "category": "out_of_scope", "difficulty": "easy", "should_refuse": True},
    {"q": "Thủ tục xin cấp lại thẻ sinh viên khi bị mất làm ở phòng nào?", "category": "out_of_scope", "difficulty": "medium", "should_refuse": True},
    {"q": "Trường có tổ chức giải bóng đá sinh viên không?", "category": "out_of_scope", "difficulty": "easy", "should_refuse": True},
    {"q": "Tiền gửi xe đạp điện mỗi tháng là bao nhiêu?", "category": "out_of_scope", "difficulty": "easy", "should_refuse": True},
    {"q": "Xe bus tuyến nào đi ngang qua cổng chính của Đại học Hải Phòng?", "category": "out_of_scope", "difficulty": "medium", "should_refuse": True}
]


def build_corpus(seed: int = 42) -> List[Regulation]:
    """
    Build Regulation objects from the mock specs.
    """
    random.seed(seed)
    regulations = []
    
    for r_data in _MOCK_DATA:
        articles = []
        for a_data in r_data["articles"]:
            clauses = []
            for c_data in a_data["clauses"]:
                clauses.append(Clause(cid=c_data["cid"], content=c_data["content"]))
            articles.append(Article(aid=a_data["aid"], heading=a_data["heading"], clauses=clauses))
        
        regulations.append(Regulation(
            rid=r_data["rid"],
            title=r_data["title"],
            category=r_data["category"],
            version=r_data["version"],
            valid_from=r_data["valid_from"],
            valid_until=r_data["valid_until"],
            issuer=r_data["issuer"],
            articles=articles
        ))
    
    return regulations


def build_qa(corpus: List[Regulation], seed: int = 42) -> List[TestQuestion]:
    """
    Extract QA from specs and add out-of-scope questions.
    """
    random.seed(seed)
    questions = []
    q_counter = 1
    
    # In-scope questions from the mock data
    for r_data in _MOCK_DATA:
        for a_data in r_data["articles"]:
            for c_data in a_data["clauses"]:
                for qa_item in c_data.get("qa", []):
                    questions.append(TestQuestion(
                        qid=f"Q{q_counter:03d}",
                        question=qa_item["q"],
                        expected=c_data["content"],  # The clause content is the expected context/answer
                        source_aids=[a_data["aid"]],
                        source_rids=[r_data["rid"]],
                        category=qa_item["category"],
                        difficulty=qa_item["difficulty"],
                        should_refuse=False
                    ))
                    q_counter += 1
    
    # Add out-of-scope questions
    for oos in _OUT_OF_SCOPE_QUESTIONS:
        questions.append(TestQuestion(
            qid=f"Q{q_counter:03d}",
            question=oos["q"],
            expected="Tôi không thể tìm thấy thông tin này trong quy chế.",
            source_aids=[],
            source_rids=[],
            category=oos["category"],
            difficulty=oos["difficulty"],
            should_refuse=oos["should_refuse"]
        ))
        q_counter += 1
        
    random.shuffle(questions)
    return questions


def build_markdown(corpus: List[Regulation]) -> str:
    """
    Build a human-readable markdown representation of the regulations.
    """
    lines = []
    lines.append("# BỘ QUY CHẾ ĐẠI HỌC HẢI PHÒNG (MOCK)")
    lines.append("")
    
    for reg in corpus:
        lines.append(f"## {reg.title}")
        lines.append(f"**Mã hiệu:** {reg.rid} | **Phiên bản:** {reg.version}")
        lines.append(f"**Danh mục:** {reg.category} | **Cơ quan ban hành:** {reg.issuer}")
        
        validity = f"Từ {reg.valid_from}"
        if reg.valid_until:
            validity += f" đến {reg.valid_until}"
        lines.append(f"**Hiệu lực:** {validity}")
        lines.append("")
        
        for art in reg.articles:
            lines.append(f"### {art.aid}: {art.heading}")
            for clause in art.clauses:
                lines.append(f"Khoản {clause.cid}. {clause.content}")
            lines.append("")
            
        lines.append("---")
        lines.append("")
        
    return "\\n".join(lines)
