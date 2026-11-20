# Kế hoạch PhoBERT, dữ liệu ngoài và review phân luồng

## 1. Quyết định mô hình

PhoBERT là họ mô hình chính cho các thí nghiệm học máy của dự án. GovDoc chỉ được dùng để tham khảo thiết kế hợp đồng đầu ra, human-in-the-loop và audit; dự án không chuyển sang Qwen làm mô hình chính và không sao chép mã GovDoc khi chưa có giấy phép rõ ràng.

## 2. Vai trò của hai bộ dữ liệu Hugging Face

### PAP_NER

- Đầu vào: ba split train/dev/test đã pin revision và chuẩn hóa dưới `data/external/pap_ner/prepared/`.
- Vai trò: fine-tune PhoBERT token classification cho các thực thể `CQ`, `VBPL`, `ĐT`, `NG`, `SL`.
- Script hiện có: `scripts/train_pap_ner.py`.
- Kết quả: external benchmark/transfer checkpoint; không phải E1–E5 nội bộ.

### OTA

- Đầu vào: PDF và các cặp Organization–Task đã pin revision; JSONL chuẩn hóa dưới `data/external/ota/prepared/`.
- Vai trò: dữ liệu chuyển giao cho bài toán liên kết cơ quan–nhiệm vụ và grounding nguồn.
- Không có: `commune_relevance`, phòng xử lý nội bộ, căn cứ chức năng hoặc `gold_unit`.
- Hiện mới có bước tải, kiểm kê và chuẩn hóa. Chưa được tuyên bố đã có mô hình PhoBERT quan hệ OTA khi chưa bổ sung trainer, split theo tài liệu và log thực tế.

Hai nguồn luôn mang cờ external/non-gold và không được trộn vào test nội bộ.

## 3. Chuỗi chuyển giao dự kiến

```text
PAP_NER --PhoBERT token classification--> checkpoint nhận diện thực thể hành chính
                                                        |
OTA --Organization–Task pairs--> relation/grounding ----+
                                                        |
gold nội bộ đã xác nhận ------------------------------> E1–E4
                                                        |
PDF/DOCX/scan test nội bộ ----------------------------> E5
```

Trainer OTA và trainer nội bộ chỉ được triển khai sau khi:

1. pilot A/B hoàn thành và hướng dẫn nhãn được khóa;
2. mọi `family_id` cần thiết cho split đã được xác nhận;
3. định nghĩa negative/candidate pair của OTA được kiểm tra để không biến cặp vắng mặt thành negative giả;
4. train/dev/test được chia theo tài liệu/nhóm gần trùng;
5. test nội bộ được khóa trước khi chọn siêu tham số.

## 4. Những ý tưởng kế thừa từ GovDoc

Dự án tự triển khai lại, không sao chép mã nguồn GovDoc:

- tách prediction khỏi quyết định cuối của con người;
- Top-1, Top-2, confidence/score, abstention và nhu cầu hội ý;
- các quyết định `accept`, `reroute`, `abstain`, `needs_review`, `out_of_scope`;
- lưu hash prediction, hash cấu hình đơn vị, reviewer và thời gian;
- audit append-only không chép toàn văn;
- không cho AI trực tiếp sửa `gold_unit`.

Hiện thực cục bộ: `scripts/review_routing.py`.

## 5. Công cụ pilot tiết kiệm thời gian

`scripts/annotate_segments.py` vẫn bảo vệ tính độc lập: không đọc file gợi ý máy, không mở gold, mỗi phiên có backup và lock. Ba phím một-chạm:

- `F5`: `task_present=0`, `commune_relevance=0`, lưu và tiếp;
- `F6`: `task_present=1`, `commune_relevance=0`, lưu và tiếp;
- `F7`: `task_present=1`, `commune_relevance=1`, lưu và tiếp.

Audit tại `evidence/annotation_audit/` lưu ID, nhãn trước/sau, hash và thời gian; không lưu `segment_text` hoặc nội dung `notes`.

Sau khi hai người hoàn thành độc lập mới chạy gợi ý máy hoặc công cụ adjudication. Gợi ý máy không bao giờ tự trở thành gold.
