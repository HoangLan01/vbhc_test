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

## 7. Đơn vị gán nhãn và ngữ cảnh

- Đối tượng gán nhãn là `annotation_unit`, không mặc định đồng nhất với block PDF thô.
- Một unit có thể ánh xạ một-một tới `segment_id` hoặc là đơn vị dẫn xuất gồm nhiều `member_segment_ids`.
- Luôn giữ mapping về segment gốc; không đổi hoặc xóa `segment_id`.
- Ưu tiên đọc unit hiện tại và ngữ cảnh ±3 segment. Dùng toàn văn cùng tài liệu khi chủ thể, tiêu đề mục hoặc phạm vi cấp xã nằm xa hơn.
- Toàn văn chỉ là căn cứ ngữ cảnh; không gán unit hiện tại là có nhiệm vụ chỉ vì nơi khác trong tài liệu có nhiệm vụ.
- Nếu text và thứ tự đọc vẫn không đủ tin cậy, đánh dấu `needs_source_check` và mở PDF/ảnh gốc.

Ba tổ hợp nhãn hợp lệ:

- `0/0`: không có nhiệm vụ;
- `1/0`: có nhiệm vụ nhưng không thuộc trách nhiệm cấp xã;
- `1/1`: có nhiệm vụ và thuộc trách nhiệm cấp xã.

`0/1` không hợp lệ.

## 8. Segment bị chia vụn

- `needs_merge` chỉ dùng khi nhiều block thực sự nối thành một đơn vị ngữ nghĩa.
- `member_segment_ids` không phải danh sách các đoạn cung cấp ngữ cảnh; không đưa các đoạn ở xa chỉ vì chúng nêu chủ thể/thời hạn.
- Các member phải cùng tài liệu, chứa segment hiện tại và không thuộc đồng thời nhiều unit.
- Header/footer, quốc hiệu, tiêu ngữ và căn cứ vẫn là mẫu âm tính hợp lệ `0/0`, không tự loại khỏi dữ liệu.
- Ký tự rác hoặc block không thể tạo đơn vị ngữ nghĩa mới dùng `exclude_invalid_unit`.
- Đơn vị ghép phải được đọc và gán nhãn lại; không tự kế thừa nhãn của một mảnh thành viên.

## 9. Adjudication và phê duyệt pilot

- Kappa/raw agreement được tính trên hai biểu độc lập trước adjudication và không tính lại như thể hai người đã đồng thuận từ đầu.
- Adjudicator phải ghi lý do cho mọi quyết định.
- Kết quả adjudication ban đầu là draft; đơn vị ghép hoặc lỗi nguồn phải được xử lý xong trước khi phê duyệt.
- Bản `approved_pilot` chỉ xác nhận pilot và quy trình, không đồng nghĩa gold toàn corpus hoặc kết quả E1–E5.
- Gợi ý máy/PhoBERT có thể hỗ trợ lô mở rộng sau khi pilot độc lập đã khóa, nhưng không tự trở thành gold.
