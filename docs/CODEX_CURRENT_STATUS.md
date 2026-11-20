# Tiến độ xác nhận đến 16/11/2026

> **BẢNG TRẠNG THÁI, KHÔNG PHẢI KẾT QUẢ THỰC NGHIỆM.** Mọi số liệu về dữ liệu người dùng phải kiểm chứng lại trên workspace của người dùng trước khi trích dẫn.

## Cập nhật đối chiếu trực tiếp ngày 19/11/2026

Phần cập nhật này mới hơn các con số bàn giao 17 văn bản/1.315 đoạn ở bên dưới:

- `documents_manifest.csv`: 79 văn bản.
- `candidate_segments.csv`: 27.973 block, 27.973 `segment_id` duy nhất, không có text trống.
- Manifest còn thiếu 62 `family_id`, 21 `doc_date`, 79 `source_url_or_archive` và 62 hàng ở các trường quyền truy cập/ẩn danh.
- Pilot v1: A/B hoàn thành 80/80; raw agreement 0,8875 và Kappa 0,6842 cho `task_present`; raw agreement 0,8750 và Kappa 0,6429 cho `commune_relevance`.
- Adjudication đã xử lý 16 trường hợp bắt buộc; một đơn vị được ghép từ bốn block có mapping.
- Pilot approved có 80 annotation units: `0/0` = 55, `1/0` = 1, `1/1` = 24.
- Bản khóa: `data/annotations/pilot_units_approved.csv` và `evidence/pilot_freezes/pilot_v1_20261119_074050_542202/`.
- Đây là pilot approved, chưa phải gold toàn corpus và chưa phải kết quả E1–E5.
- Hai bộ dữ liệu ngoài PAP_NER và OTA đã được pin/chuẩn hóa; PhoBERT PAP_NER có script huấn luyện nhưng chưa có full GPU run được xác nhận.
- Bước tiếp theo: hoàn thiện metadata/family, tạo annotation units ổn định toàn corpus rồi mới chọn lô mở rộng; xem `docs/GOLD_EXPANSION_PLAN.md`.
- G0 đã tạo 27.970 unit proposals và mapping phủ đủ 27.973 segment; 7.675 unit cần review phân đoạn, 20.215 identity proposal, 80 pilot approved.
- Có 3 cặp family gợi ý; chưa tự cập nhật `family_id`.
- `manifest_metadata_review.csv` đã hoàn tất 79/79 và áp dụng có backup; manifest không còn ô metadata bắt buộc trống, ID/filename/SHA-256 không đổi.
- G0 đã refresh: 79/79 tài liệu metadata-ready và 20.215 unit identity mới đủ điều kiện lấy mẫu; 7.675 unit vẫn cần review phân đoạn.
- Batch 01 đã tạo 240 unit từ đủ 79 tài liệu, không trùng pilot; A/B đang 0/240 và chưa có nhãn.
- `annotate_units.py` hỗ trợ ngữ cảnh ±3/toàn văn, F5/F6/F7, backup/lock/audit và không hiển thị heuristic.

## 1. Môi trường đã xác nhận

- Windows 11 + VS Code; người dùng làm việc tại `D:\2025\src\SF2026_Research_Kit`.
- Python 3.11 đã dùng để tạo `.venv`; lệnh `python scripts/workflow.py init` đã chạy thành công.
- Tesseract OCR đã được Windows nhận diện qua PATH; `tesseract --list-langs` trả về `eng`, `osd`, `vie`. Không cần Ubuntu/WSL/Docker.

## 2. Ingest đã chạy

Lệnh:

```powershell
.\.venv\Scripts\python.exe scripts\workflow.py ingest
```

Đầu ra người dùng đã báo:
- **17 file PDF**, **1.315 đoạn** được đọc.
- Một cảnh báo: file `5. Nhân lực phụ trách CNTTCĐS.pdf`, **trang 3** cần OCR/kiểm tra.
- Khi chạy `ingest` đầu tiên, terminal có cảnh báo `fitz API is deprecated`; không làm dừng xử lý.

Đối chiếu trên **bản `candidate_segments.csv` đã gửi trong cuộc trò chuyện**:
- 1.315 dòng; 17 `document_id`; 1.315 `segment_id` duy nhất.
- Trường hiện có: `document_id`, `segment_id`, `source_location`, `segment_text`.
- 365 đoạn có dưới 20 ký tự.
- 393 dòng thuộc nhóm `segment_text` lặp ít nhất một lần (nhiều thể thức/tiêu ngữ/số trang); không đồng nghĩa 393 lỗi hoặc văn bản trùng.
- Không có dòng nguồn `page:3` đối với `document_id` bắt đầu bằng `5_` trong **bản CSV đã cung cấp**. Chưa xác nhận trang đó trắng hay đã OCR lại; không kết luận rằng OCR thất bại nếu chưa mở PDF gốc.
- Một số bảng bị phân mảnh thành nhiều đoạn; đoạn ngắn không được xóa hàng loạt vì có thể chứa thời hạn/chủ thể.
- Dataset hiện tập trung chủ yếu vào văn bản của một phường, cần thận trọng khi khái quát hóa.

**Chưa có xác nhận người dùng đã chạy lại `ingest --ocr --force`**, chưa có bản CSV mới sau OCR. Không được chạy ghi đè tự động.

## 3. Mã nguồn hiện tại

- `scripts/workflow.py` có các lệnh: `init`, `ingest`, `prepare-annotations`, `validate`, `qc-labels`, `split`, `predict-detection`, `evaluate-detection`, `predict-routing`, `evaluate-routing`, `evaluate-extraction`, `evaluate-e5`, `audit`.
- Đã có baseline sơ bộ rule/embedding/hybrid; **không có** script huấn luyện PhoBERT/LLM.
- E3 hiện đánh giá Exact Match ở điều kiện `task_id` gold (oracle); **không** phải đo E5.
- E5 hiện là chỉ số theo mẫu số gold, **chưa tính FP dự đoán thừa** để công bố Precision/F1 cuối chuỗi.
- `config/units.json` cần bổ sung chức năng và căn cứ đúng của các phòng; ví dụ giả không dùng cho nghiên cứu.
- Các lệnh `ingest`, `prepare-annotations`, `split` có cơ chế hạn chế ghi đè; `--force` vẫn có nguy cơ mất dữ liệu hoặc đổi ID.

## 4. Chưa thực hiện/chưa có bằng chứng

- Chưa hoàn tất metadata của 17 văn bản trong `documents_manifest.csv` (cần kiểm tra file thật).
- Chưa có bộ nhãn `segments_gold`/`tasks_gold` được con người duyệt và xác nhận (theo thông tin cuộc trò chuyện).
- Chưa thực hiện kiểm tra thống nhất giữa hai người gán nhãn.
- Chưa có tập train/dev/test chính thức và chưa chốt phiên bản danh mục phòng, nhãn.
- Chưa có thí nghiệm E1–E5 dùng nhãn/dữ liệu thật được đánh giá đầy đủ.
- Chưa có kết quả khoa học để điền lại Bảng 3/Hình 3.
- Chưa hoàn tất ví dụ truy vết, hình vector, template hội thảo, literature matrix.

## 5. Công việc gần nhất

1. Audit workspace **chỉ đọc**: kiểm tra CSV, mã, `git status` (nếu có repo), tập file, hàng trống/trùng, trang OCR và tên cột.
2. Xác nhận trạng thái trang 3 của PDF số 5 từ file gốc; nếu là ảnh có nội dung, hướng dẫn OCR an toàn có bản sao lưu trước; KHÔNG tự chạy `--force`.
3. Hỗ trợ chỉnh/sinh **báo cáo chất lượng dataset ở chế độ không phá hủy**; chuẩn bị tập pilot 50–100 đoạn đa dạng có mẫu âm tính, vẫn giữ `segment_id` gốc.
4. Xây dựng/đối chiếu quy tắc gán nhãn với `docs/ANNOTATION_GUIDE.md`; quyết định khi nào đoạn được tách thành nhiều `task_id`.
5. Sau khi người dùng đồng ý: tạo biểu pilot, làm QC, rồi mở rộng gold. Chỉ khi gold đủ tốt mới triển khai mô hình/metric.
