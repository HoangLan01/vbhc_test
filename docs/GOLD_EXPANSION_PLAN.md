# Kế hoạch mở rộng gold sau pilot v1

## Mục tiêu

Mở rộng nhãn nội bộ cho E1/E2 và tạo nền cho E3/E4/E5 mà không phá ID, không dùng dự đoán làm gold và không chia rò rỉ theo đoạn.

## Quality gate trước khi chọn lô mới

Theo kiểm kê workspace ngày 19/11/2026:

- 79 văn bản, 27.973 block ứng viên;
- 62 văn bản còn thiếu `family_id`;
- 21 văn bản còn thiếu `doc_date`;
- 79 văn bản chưa điền `source_url_or_archive`;
- 62 văn bản còn thiếu `permission_basis`, `access_level` hoặc `anonymized`;
- 7.696 block dưới 20 ký tự và 8.873 hàng thuộc nhóm text trùng chính xác.

Không sinh lô gold mở rộng cho đến khi:

1. quyền sử dụng và mức truy cập của tài liệu trong lô được xác nhận;
2. `family_id` của mọi tài liệu liên quan được điền;
3. thuật toán tạo annotation unit toàn corpus có mapping và QC;
4. các unit quá ngắn/bảng/OCR được gắn cờ để không lặp lại lỗi pilot;
5. split theo tài liệu/nhóm gần trùng được khóa trước khi dùng test.

## Các pha triển khai

### G0 — Chuẩn hóa annotation unit

- Sinh unit dẫn xuất cho toàn corpus nhưng không sửa `candidate_segments.csv`.
- Giữ `annotation_unit_id`, `member_segment_ids`, vị trí nguồn và hash text.
- Báo cáo số unit một-một, unit ghép, lỗi OCR, bảng và unit cần kiểm tra nguồn.
- Kiểm tra thủ công mẫu từ từng loại tài liệu trước khi chọn nhãn.

### G1 — Lô mở rộng đầu tiên

- Mục tiêu vận hành ban đầu: khoảng 240 unit để có tối thiểu khoảng 3 unit từ mỗi văn bản, không phải cỡ mẫu cuối cùng.
- Loại trừ toàn bộ unit pilot v1 khỏi lô mới bằng mapping segment.
- Phân tầng theo tài liệu, độ dài, tín hiệu nhiệm vụ, bảng/OCR và trùng lặp.
- Hai người gán độc lập; gợi ý PhoBERT/luật bị ẩn trong giai đoạn độc lập.
- QC và adjudication giống pilot v1.

Con số 240 là kích thước vòng vận hành để kiểm tra khả năng mở rộng, không được mô tả là cỡ mẫu đã chứng minh thống kê hoặc bộ train cuối.

### G2 — Mở rộng có hỗ trợ mô hình

- Dùng PAP_NER để tiền huấn luyện PhoBERT NER và OTA cho chuyển giao Organization–Task khi trainer quan hệ đã được kiểm chứng.
- PhoBERT/luật chỉ xếp ưu tiên hoặc tạo suggestion riêng.
- Người gán xác nhận/sửa mọi hàng; suggestion không tự trở thành gold.
- Chọn thêm mẫu dựa trên độ không chắc chắn và bao phủ tài liệu, đồng thời giữ một phần lấy mẫu ngẫu nhiên để tránh bias active learning.
- Quy mô mỗi vòng quyết định bằng learning curve và phân bố nhãn quan sát được, không chỉnh dựa trên test.

### G3 — Khóa train/dev/test

- Chia theo `family_id`/`document_id`, không theo unit.
- Dev dùng chọn checkpoint/ngưỡng; test chỉ dùng cuối cùng.
- Các tài liệu test phục vụ E5 phải được gán đầy đủ mọi nhiệm vụ trong tài liệu để đếm TP/FP/FN.
- Hash split, gold, config, code và model được lưu trong evidence.

## Phạm vi của hai bộ dữ liệu ngoài

- PAP_NER: external token classification/NER transfer.
- OTA: external Organization–Task relation/grounding transfer.
- Không nguồn nào cung cấp `commune_relevance` hoặc `gold_unit` nội bộ.
- Không trộn test ngoài với test nội bộ và không dùng metric ngoài làm E1–E5.

## Điểm dừng

Chưa chạy huấn luyện nội bộ nếu chưa có:

- annotation units ổn định;
- gold approved đủ dùng;
- `split_manifest.csv` khóa theo family;
- prediction/evaluator lưu từng mẫu;
- cấu hình đơn vị và căn cứ chức năng có hiệu lực cho E4.

## Trạng thái triển khai G0 ngày 19/11/2026

- Đã tạo 27.970 annotation-unit proposals phủ đúng một lần toàn bộ 27.973 segment.
- 80 unit pilot approved được tái sử dụng.
- 20.215 unit identity proposal.
- 7.675 unit `needs_segmentation_review`; không tự động ghép.
- Mapping có 27.973 hàng, không thiếu/trùng segment.
- Có 3 cặp tài liệu gần trùng được gợi ý để người dùng xem xét family.
- Metadata review đã hoàn tất và áp dụng có backup: 79/79 tài liệu metadata-ready.
- Proposal G0 đã refresh sau metadata: 20.215 unit mới đủ điều kiện lấy mẫu; 7.675 unit ngắn vẫn ở quality gate segmentation review.
- `data/annotations/manifest_metadata_review.csv` có 79/79 hàng approved; identity document/hash không thay đổi khi apply.

Các file G0 đều mang trạng thái non-gold và không được dùng trực tiếp để huấn luyện/đánh giá.

## Trạng thái batch 01 ngày 20/11/2026

- Đã chọn 240 annotation units, seed 43, từ đủ 79 tài liệu.
- Một tài liệu chỉ có 2 unit eligible; 74 tài liệu có 3 unit và 4 tài liệu có 4 unit.
- Không unit nào trùng pilot v1.
- Heuristic selection: 91 task-signal, 149 không task-signal; đây không phải nhãn.
- A/B có 240 hàng giống nhau, nhãn trống và không chứa cột heuristic.
- GUI `scripts/annotate_units.py` đã sẵn sàng; chưa bắt đầu gán batch 01.
