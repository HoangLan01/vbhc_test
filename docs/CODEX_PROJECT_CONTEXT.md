# Bối cảnh khoa học, phản biện và yêu cầu triển khai

Cập nhật bàn giao: 16/11/2026. Tài liệu này tổng hợp cuộc làm việc trước trong ChatGPT để Codex ở VS Code có thể tiếp tục. **Phải đối chiếu lại file thật ở workspace khi sử dụng.**

## 1. Công trình đang thực hiện

- Tên bài: **NGHIÊN CỨU PHƯƠNG PHÁP TRÍCH XUẤT VÀ PHÂN LUỒNG NHIỆM VỤ TỪ VĂN BẢN HÀNH CHÍNH TIẾNG VIỆT**.
- Hội thảo: SF2026, mã bài trên CMT: **216**. Người dùng đã xác nhận vẫn được sửa/nộp; không coi thời hạn là rào cản hiện tại và không tự khẳng định bài đã được nhận đăng.
- Hướng gắn với đề án tốt nghiệp thạc sĩ: văn bản hành chính Việt Nam, bối cảnh mô hình chính quyền địa phương hai cấp. Không đồng nhất trích xuất với phân công nội bộ.
- Manuscript ban đầu 12 trang, có phần đề xuất phương pháp và kế hoạch thực nghiệm. Bản sửa vòng 1 đã chỉnh nội dung nhưng CHƯA có kết quả thực nghiệm.
- Tài liệu gốc có thể được người dùng đưa vào `paper/` sau này: `HTKHQG-Nguyễn Hoàng Lân.docx`, `Conference Management Toolkit - View reviews.pdf`, `HTKHQG_Nguyen_Hoang_Lan_ban_chinh_sua_vong_1.docx`, `Ghi_chu_chinh_sua_vong_1.md`. Không giả định chúng đã tồn tại trong máy người dùng.

## 2. Đánh giá phản biện — phải đáp ứng thật

**Reviewer #1:** chủ đề thời sự, yêu cầu đúng template kỷ yếu, tăng chất lượng hình, kết luận ngắn và chỉ nêu kết quả nổi bật; điểm tổng thể 4.

**Reviewer #3:** đánh giá bài chủ yếu là khung nghiên cứu; điểm tổng thể 2 và đề nghị **Major Revision**. Sáu điểm bắt buộc:
1. Chưa có kết quả thực nghiệm đã kiểm chứng cho trích xuất và phân luồng.
2. Bảng 3/Hình 3 trong bản cũ có Precision/Recall/F1 cụ thể nhưng các phần khác ghi chưa kiểm thử. **Không có bằng chứng nguồn số liệu**; phải bỏ/ghi rõ minh họa hoặc thay bằng số liệu đo thật, không diễn giải như kết quả thực.
3. Chưa chứng minh đóng góp mới so với regex, PhoBERT, embedding, LLM có sẵn.
4. Thiếu thống kê dataset thực, phân bố nhãn, quy trình gán và QC độc lập.
5. Chưa có cấu hình đủ tái lập của từng phương pháp, embedding, prompt, các quy tắc phân luồng theo chức năng/thẩm quyền.
6. Thiếu so sánh công bằng và end-to-end, đặc biệt tác động lỗi OCR → trích xuất → phân luồng.

Bốn gợi ý cải thiện: ví dụ đầu vào→bản ghi→gợi ý có truy vết; ghi rõ Hình 4 là prototype; chi phí/tài nguyên/bảo mật/xác nhận người dùng; thống nhất thuật ngữ và trình bày.

## 3. Bài toán và đóng góp mục tiêu (chưa phải kết quả)

Đầu vào: DOCX, PDF text, PDF scan/ảnh khi cần OCR.

- **A:** phát hiện đoạn/câu có nhiệm vụ, phân biệt giao việc với mô tả kết quả đã thực hiện.
- **B:** quyết định nhiệm vụ có liên quan trách nhiệm UBND xã/phường; không coi việc “nhắc đến UBND xã/phường” đồng nghĩa giao việc.
- **C:** tạo `task_text`, `source_actor`, `actor_role`, `deadline_raw`, `deadline_iso`, `deadline_type`, `deliverable`, `source_location`; liên kết đúng theo từng `task_id`, không tạo thông tin ngoài văn bản.
- **D:** gợi ý `gold_unit`/phòng chủ trì từ nội dung nhiệm vụ + mô tả chức năng/thẩm quyền tại thời điểm phù hợp; phải phân biệt **source actor trong văn bản** với **gợi ý đơn vị xử lý nội bộ**. Hệ thống cần cho phép từ chối gợi ý khi thiếu căn cứ và có thao tác cán bộ xác nhận.

Đóng góp có tiềm năng: mô hình hóa chuỗi nghiệp vụ hai cấp, bộ dữ liệu gán nhãn có truy vết, cơ chế phân luồng embedding + ràng buộc chức năng/hiệu lực tổ chức, so sánh với luật/embedding, ablation, E5. Chỉ tuyên bố đóng góp sau khi có bằng chứng.

## 4. Ma trận thực nghiệm

| Thí nghiệm | Phạm vi | Đầu ra/chỉ số |
|---|---|---|
| E1 | Phát hiện đoạn/nhiệm vụ | TP/FP/FN, Precision, Recall, F1 theo cấp đánh giá công bố |
| E2 | Phân loại liên quan cấp xã | P/R/F1, ma trận nhầm lẫn; đầu vào gold vs predicted phải phân biệt |
| E3 | Trích xuất và liên kết nội dung/đơn vị/thời hạn/sản phẩm | F1 từng trường, span/quan hệ, Exact Match bản ghi; oracle alignment không phải E5 |
| E4 | Gợi ý phòng trên nhiệm vụ gold | Top-1, Top-2, macro-F1, coverage/abstention; đối chứng rule/embedding/hybrid |
| E5 | DOCX/PDF/scan → nhiệm vụ + phòng | Đánh giá ghép dự đoán/gold 1-1, tính cả FP/FN, kết quả đúng hoàn chỉnh; ảnh hưởng OCR, chi phí và thời gian |

Kiểm soát rò rỉ: chia theo `document_id`/`family_id`, không chia ngẫu nhiên theo từng câu trong cùng tài liệu. Chọn tham số trên dev; test chỉ dùng đánh giá cuối.

## 5. Phương pháp triển khai

- Ingest: PyMuPDF, python-docx; OCR Tesseract (`vie+eng`).
- Baseline A/B/C: luật, regex, từ khóa; xử lý nhận diện thời hạn/đơn vị cần truy vết.
- PhoBERT: đối chứng NLP tiếng Việt, cần script huấn luyện/gán nhãn và tách từ phù hợp; hiện CHƯA triển khai.
- Embedding: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` là mặc định cho routing trong bộ khung, không tuyên bố là tốt nhất.
- Hybrid: `alpha * S_semantic + (1-alpha) * S_keyword` kết hợp lọc ứng viên theo căn cứ chức năng/thời điểm. Alpha 0.75 trong code chỉ là mặc định, KHÔNG phải siêu tham số đã được tối ưu.
- LLM: nghiên cứu ứng viên LLM có JSON schema và căn cứ nguồn; hiện CHƯA triển khai/chạy thử. Chỉ sử dụng dữ liệu được phép gửi lên dịch vụ bên ngoài.
- Đánh giá phải có log, config, prediction trên từng mẫu, version mô hình, n, và trường hợp sai cụ thể; không dùng biểu đồ minh họa làm bằng chứng.

## 6. Nguồn tài liệu và mẫu bài

- `README.md`, `docs/QUY_TRINH_8_MUC.md`, `docs/ANNOTATION_GUIDE.md`, `docs/REVIEW_RESPONSE_TEMPLATE.md` hiện có trong bộ khung.
- Bản gốc review, bản báo cáo/bài báo đã sửa có thể do người dùng cung cấp thêm vào `paper/`. Khi sửa văn bản khoa học phải mở đọc đúng bản được chỉ định và giữ vết thay đổi.
- Template SF2026 chính thức: chưa có trong workspace; không tự suy luận giới hạn trang từ hướng dẫn khác năm.
- Công trình liên quan cần rà soát thực sự: văn bản hành chính tiếng Việt/IE ở cấp tài liệu, PhoBERT, Sentence-BERT, structured LLM, phân luồng theo chức năng đơn vị. Không bịa DOI hoặc kết quả nghiên cứu.

## 7. Yêu cầu trả lời người dùng

Trao đổi bằng tiếng Việt, đi từng bước có lệnh PowerShell chạy được trên Windows; sau mỗi bước ghi rõ: (i) file đầu vào; (ii) lệnh; (iii) file đầu ra; (iv) cách kiểm tra; (v) giới hạn. Không báo đã hoàn tất 8 mục khi mới có dữ liệu đọc thô.
