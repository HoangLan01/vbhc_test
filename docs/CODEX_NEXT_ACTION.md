# Hành động Codex nên thực hiện khi nhận bàn giao

## Ưu tiên hiện tại sau khi khóa pilot v1 (19/11/2026)

Pilot v1 đã hoàn tất và được snapshot. Không tạo lại/ghi đè pilot. Công việc kế tiếp theo thứ tự:

1. Hoàn thiện `family_id`, nguồn/quyền dùng, mức truy cập và ẩn danh cho tài liệu dự kiến đưa vào gold.
2. Thiết kế/sinh annotation units toàn corpus có mapping về `segment_id`; không chọn trực tiếp từ 27.973 block thô.
3. QC unit quá ngắn, bảng, OCR và thứ tự đọc trên mẫu đa dạng.
4. Chỉ sau khi các quality gate đạt mới tạo lô mở rộng đầu tiên theo `docs/GOLD_EXPANSION_PLAN.md`.
5. PAP_NER/OTA chỉ dùng chuyển giao ngoài; không trộn vào gold/test nội bộ.

Các mục bàn giao ban đầu dưới đây được giữ làm lịch sử, không thay thế trạng thái mới.

## Yêu cầu đầu tiên (chỉ kiểm tra, không sửa dữ liệu)

**Mục tiêu:** Đánh giá mức sẵn sàng của dự án trên Windows và thiết kế an toàn cho lô gán nhãn thử.

1. Đọc đầy đủ: `AGENTS.md`, `docs/CODEX_PROJECT_CONTEXT.md`, `docs/CODEX_CURRENT_STATUS.md`, `README.md`, `docs/ANNOTATION_GUIDE.md` và `scripts/workflow.py`.
2. Kiểm tra trên đĩa `data/processed/candidate_segments.csv` (khi có) để xác nhận 17 văn bản, 1.315 đoạn và các vị trí nguồn; nếu không có file hoặc khác với trạng thái bàn giao thì báo rõ.
3. Kiểm tra `data/processed/documents_manifest.csv` với các trường `family_id`, `doc_date`, `doc_type`, `source_url_or_archive`, `permission_basis`, `access_level`, `anonymized`.
4. Kiểm tra tệp PDF số 5 / trang 3 có thực sự cần OCR hay chỉ là trang trắng. Nếu không có tệp gốc hoặc chưa đủ phương tiện đọc trang, nói rõ không thể xác minh.
5. Kiểm tra `prepare-annotations` đang hành xử thế nào, có nguy cơ đè `segments_gold.csv` không; không chạy nếu chưa được yêu cầu.
6. Đề xuất **bản thiết kế chọn mẫu pilot 50–100 đoạn** có nhiệm vụ/không có nhiệm vụ, nguồn đa dạng, các đoạn dài/ngắn và trường hợp nhiều phòng; không gán nhãn gold bằng máy rồi coi là sự thật.
7. Lập bảng ngắn `đã có / thiếu / bước tới / file cần chỉnh`, hỏi/đề nghị một hành động duy nhất để người dùng triển khai.

**Đầu ra lần đầu:** báo cáo rà soát ngắn gọn bằng tiếng Việt, không thay đổi file.

## Sau khi được phép lập trình

Ưu tiên các sửa đổi nhỏ, có test:
1. Thêm công cụ kiểm tra chất lượng CSV và xuất bảng tổng hợp dưới `results/` mà không đụng file gốc.
2. Nếu cần, bổ sung OCR kiểm tra **một trang được chọn** và so sánh text gốc/OCR trước khi quyết định nhập lại; tuyệt đối không đổi 1.315 `segment_id` đã có nếu không lập ánh xạ.
3. Thêm công cụ lựa chọn pilot có seed cố định, lưu `segment_id`/`document_id`/`source_location`/đoạn nguồn và cột gán nhãn trống; tuyệt đối không điền `approved` thay con người.
4. Chuẩn bị 2 bản biểu gán nhãn cho A/B cùng những `segment_id`, hỗ trợ QC và thống nhất nhãn.
5. Tạo `tasks_gold` từ nhãn đã xác nhận, có cơ chế liên kết nguồn; bảo toàn danh sách nhiệm vụ âm tính.
6. Sau khi dataset gold sẵn sàng, lập test unit/fixture giả rõ ràng, rồi chạy baseline E1/E2/E4 trên dev; không chạy test trước thời điểm khóa mô hình.

## Điều kiện báo hoàn thành

Bất kỳ công việc nào được thông báo là hoàn tất phải ghi rõ: file đã tạo/sửa, lệnh đã chạy, kiểm thử đã thực hiện, số liệu thật quan sát được và hạn chế còn tồn tại. Không điền chỉ số từ ví dụ giả lập vào bài báo.
