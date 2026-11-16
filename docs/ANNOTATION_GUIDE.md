# HƯỚNG DẪN GÁN NHÃN SƠ BỘ – phiên bản 0.1

Tài liệu này là bản dự thảo cần thống nhất với Thầy và người gán nhãn trước khi khóa dataset.

## 1. Cấp văn bản
Ghi `document_id`, số/ký hiệu, ngày, loại văn bản, nguồn, quyền sử dụng và `family_id` (nhóm tài liệu liên quan hoặc gần trùng). Không tự suy ra ngày nếu OCR mờ; ghi chưa xác định.

## 2. Cấp đoạn (`segments_gold.csv`)
- `task_present=1` khi đoạn thể hiện công việc/hành động phải thực hiện (giao, yêu cầu, chỉ đạo, đề nghị, phối hợp...); `0` khi chỉ mô tả, viện dẫn hoặc thông tin không giao việc.
- `commune_relevance=1` khi đoạn chứa nhiệm vụ liên quan trách nhiệm UBND xã/phường; `0` nếu không. Đối với đoạn cần ngữ cảnh ở mục trên, người gán phải kiểm tra ngữ cảnh và ghi lý do vào `notes`.
- `label_status=approved` sau khi thống nhất. Trước đó dùng `draft` hoặc `needs_review`.
- Phải giữ cả các đoạn có `task_present=0` để đánh giá false positives.

## 3. Cấp nhiệm vụ (`tasks_gold.csv`)
- Một nhiệm vụ = một hành động có thể theo dõi riêng, gắn người/cơ quan thực hiện và sản phẩm/thời hạn nếu có căn cứ; các tác vụ con cùng sản phẩm/thời hạn có thể được gom theo quy tắc thống nhất.
- `source_text`: trích nguyên cụm/đoạn nguồn; `task_text`: nội dung nhiệm vụ rõ ý nhưng KHÔNG tự diễn giải thêm.
- `source_actor`: cơ quan nhận nhiệm vụ được NÊU TRONG văn bản. `actor_role`: chủ trì/phối hợp/thông tin/không rõ.
- `gold_unit`: phòng được CHUYÊN GIA/NGƯỜI CÓ THẨM QUYỀN xác nhận theo căn cứ chức năng; không lấy theo dự đoán AI. Cần `evidence_unit` và `routing_as_of` (thời điểm áp dụng phân công).
- `deadline_raw`: chuỗi nguồn; `deadline_iso`: YYYY-MM-DD khi có ngày cụ thể; `deadline_type`: trước ngày/chậm nhất/định kỳ/trong khoảng/không rõ. Không đổi “trước ngày X” thành “đến hết X”.
- `deliverable`: báo cáo, danh sách, kế hoạch, kết quả cụ thể nếu văn bản có nêu; để trống khi không nêu.
- Không đủ căn cứ phân luồng => đánh dấu `needs_review`, KHÔNG gán bừa vào 1 trong các phòng.

## 4. Tình huống khó phải thống nhất
- Nhiều động từ trong một câu: tách hay không tách nhiệm vụ?
- Đối tượng được nêu ở đoạn đầu, thời hạn ở cuối văn bản.
- Chủ trì và phối hợp cùng được nêu.
- Nhiệm vụ liên quan nhiều lĩnh vực, một phòng chủ trì và nhiều phòng phối hợp.
- Cơ cấu 3/5 phòng và văn bản phân công thay đổi theo thời gian.
- OCR sai ngày, số ký hiệu, tên cơ quan, tên văn bản.

## 5. Kiểm tra độc lập
Hai người gán cùng danh sách segment, không xem nhãn nhau. Dùng `qc-labels` để đo tỷ lệ thống nhất và Cohen's Kappa cho hai nhãn 0/1; tất cả bất đồng phải được quyết định lại bằng căn cứ. Riêng span/tách task và `gold_unit` cần bảng đối soát thủ công và ghi người kiểm tra.

## 6. Tách dataset
Dùng `family_id` bảo đảm tài liệu gần trùng không xuất hiện ở nhiều tập. Khóa tập test và không xem nhãn test khi chỉnh luật/siêu tham số.
