# AGENTS.md — Dự án nghiên cứu SF2026

> HƯỚNG DẪN BẮT BUỘC CHO CODEX KHI MỞ WORKSPACE NÀY.
> Đây là công trình khoa học đang triển khai, KHÔNG phải ứng dụng đã hoàn thiện.

## 1. Đọc bối cảnh trước khi làm việc

Trước khi sửa hoặc chạy mã nguồn:
1. Đọc `docs/CODEX_PROJECT_CONTEXT.md` (đề tài, reviewer và thiết kế nghiên cứu).
2. Đọc `docs/CODEX_CURRENT_STATUS.md` (sự thật đã xác nhận, tiến độ, giới hạn).
3. Đọc `docs/CODEX_NEXT_ACTION.md` (bước ưu tiên, yêu cầu nghiệm thu).
4. Đọc `README.md`, `docs/ANNOTATION_GUIDE.md`, `docs/QUY_TRINH_8_MUC.md`.
5. Kiểm tra **mã nguồn thực tế** trong `scripts/workflow.py` và dữ liệu hiện có; tài liệu bàn giao không thay thế kiểm tra file trên máy.

## 2. Mục tiêu

Bài báo: **“Nghiên cứu phương pháp trích xuất và phân luồng nhiệm vụ từ văn bản hành chính tiếng Việt”** (CMT SF2026, paper ID 216), gắn với luận văn thạc sĩ về chính quyền địa phương hai cấp. Hướng đóng góp trọng tâm là phân biệt (a) nhiệm vụ/đối tượng được nêu trong văn bản với (b) gợi ý đơn vị xử lý nội bộ, có căn cứ chức năng/thẩm quyền, truy vết và con người xác nhận.

Bốn tác vụ: A phát hiện nhiệm vụ; B xác định nhiệm vụ thuộc phạm vi UBND xã/phường; C trích xuất và liên kết nội dung, chủ thể, thời hạn, sản phẩm, nguồn; D gợi ý phòng/đơn vị xử lý nội bộ.

Thí nghiệm E1–E5 phải được đánh giá đúng mức: E1 phát hiện đoạn/nhiệm vụ; E2 lọc phạm vi; E3 trích xuất trường và liên kết; E4 phân luồng với nhiệm vụ gold (oracle); E5 đầu cuối từ tài liệu thực (bao gồm OCR khi phù hợp).

## 3. Quy tắc liêm chính nghiên cứu — không được vi phạm

- KHÔNG tạo, sửa, bịa đặt, nội suy các số đo Precision/Recall/F1/Top-k/Exact Match để lấp bảng; không được coi số liệu giả lập là kết quả khoa học.
- Bảng 3/Hình 3 ở bản bài báo gốc có số liệu chưa được chứng minh; bản chỉnh sửa vòng 1 đã loại bỏ/để chỗ trống. Mọi kết quả phải sinh từ prediction + ground truth + cấu hình + log có thể kiểm chứng.
- Không tự tạo nhãn gold từ dự đoán mô hình. Nhãn cần con người xác nhận, với căn cứ nguồn và căn cứ phân luồng.
- Giữ nguyên `document_id`, `segment_id`, `task_id` đang sử dụng; không tự ý đổi chúng hoặc tách/ghép hàng mà không có bản ánh xạ và lý do.
- Không chạy `ingest --force`, `prepare-annotations --force`, `split --force` hoặc lệnh ghi đè khi chưa sao lưu và thông báo rõ ảnh hưởng. Không xóa dữ liệu gốc, nhãn, kết quả và log.
- Phải chia train/dev/test **theo tài liệu/nhóm gần trùng**; chọn thông số bằng dev, không chỉnh theo test. Không gọi kết quả E3 dùng `task_id` gold là end-to-end.
- Không tuyên bố đã fine-tune PhoBERT, chạy LLM hoặc có E5 nếu chưa có mô hình/log/đánh giá thực tế.
- Trả lời và chú thích mã nguồn **bằng tiếng Việt rõ ràng**; giải thích trước mọi thay đổi có khả năng làm mất dữ liệu.

## 4. Dữ liệu công vụ và bảo mật

- File trong `data/raw/`, `data/processed/`, `data/annotations/` có thể chứa thông tin cơ quan và dữ liệu cá nhân; không in/đưa toàn văn vào báo cáo chat khi không cần, không commit hoặc đẩy lên kho công khai.
- Không gửi dữ liệu thực tế lên API/LLM/cloud hoặc bên thứ ba khi chưa được người dùng xác nhận đủ quyền sử dụng.
- Dữ liệu `config/units_EXAMPLE_ONLY.json` chỉ là ví dụ; không dùng để tính điểm công bố. `config/units.json` phải dựa trên chức năng/thẩm quyền có căn cứ và thời gian hiệu lực; không tự suy đoán phòng chủ trì.
- Đừng chỉnh `.gitignore` để đưa dữ liệu gốc hoặc kết quả nhạy cảm vào Git. Không tự ý upload lên GitHub.

## 5. Môi trường và cách làm việc

- Máy người dùng: Windows 11, VS Code, Python 3.11, virtualenv `.venv`, Tesseract với `eng`, `osd`, `vie` đã nhận diện.
- Tại root workspace, dùng PowerShell và đường dẫn Python trực tiếp:
  ` .\.venv\Scripts\python.exe scripts\workflow.py --help `
- Không yêu cầu Ubuntu, WSL2 hoặc Docker cho các công đoạn đầu. Nếu gặp vấn đề môi trường, chẩn đoán trên Windows trước.
- Chỉ sửa những file cần cho tác vụ; ưu tiên thay đổi nhỏ, có test, không làm hỏng CSV đang gán nhãn. Mỗi thay đổi chức năng nên có kiểm thử trên dữ liệu không nhạy cảm, rồi kiểm tra đầu ra thực tại máy người dùng.
- Khi bắt đầu phiên mới: trước tiên tổng hợp “đã xác nhận / chưa xác nhận / bước tiếp theo”, không mặc định tài liệu này luôn mới; đối chiếu file thật.

## 6. Bước đang ưu tiên

**Không huấn luyện mô hình ngay.** Kiểm tra chất lượng 17 văn bản/1.315 đoạn, xử lý trang 3 của văn bản số 5 (cảnh báo OCR), kiểm tra metadata và thiết kế đợt gán nhãn thử 50–100 đoạn có cả mẫu âm tính. Sau đó mới tiến tới `segments_gold.csv` / `tasks_gold.csv`, QC giữa hai người gán và baseline E1/E2.

Trong lần đầu được yêu cầu “tiếp tục dự án”: CHỈ đọc/audit, đưa kế hoạch và chỉ rõ file; không chạy lệnh ghi đè hoặc chỉnh sửa dữ liệu khi người dùng chưa yêu cầu.
