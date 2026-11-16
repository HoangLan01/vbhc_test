# BẢNG NGHIỆM THU TỪNG MỤC (KHÔNG THAY THẾ KẾT QUẢ THỰC NGHIỆM)

| Mục | Công việc | Chứng cứ tối thiểu | Nghiệm thu khi | Mục bài báo |
|---|---|---|---|---|
| 1 | Thu thập và chuẩn hóa dataset | manifest, hash, nguồn/quyền dùng, số lượng văn bản, nhiệm vụ, phân bố loại/năm, thống kê OCR | Có số thực, kiểm tra thủ công, không dùng tài liệu trái phép | 4.1–4.2, 5.1 |
| 2 | Gán nhãn độc lập | hướng dẫn, 2 bộ nhãn độc lập trên tập giao nhau, QC kappa cho phân loại, conflict+adjudication, nhãn gold | Có người duyệt và quy tắc giải quyết bất đồng | 4.1, 5.1 |
| 3 | Chạy baseline và mô hình | source code, phiên bản, seed, train/dev/test, params, prompt nếu LLM, log, hash | Có predictions ở mức mẫu; mô hình nào chưa chạy được nêu rõ | 4.3–4.6 |
| 4 | Thực nghiệm E1–E5 | CSV dự đoán, bảng metric, error logs, phân tích OCR, confusion | Chỉ số đo trên test khóa, định nghĩa đúng mẫu số và tiêu chí khớp | 5.1–5.4, 6 |
| 5 | Ví dụ truy vết | văn bản gốc có quyền dẫn + span + output + unit evidence + cách người duyệt | Mỗi nhận định nối lại được tới căn cứ nguồn | 3.2, 5.4 |
| 6 | Hình ảnh | bản gốc vector, file xuất, kiểm tra 100% zoom/in | Chữ đọc được, sơ đồ phản ánh đúng quy trình đã chạy | Hình 1–2–3 |
| 7 | Mẫu cuối | template chính thức, checklist form, bản soát số trang | Đúng mẫu/version do hội thảo cung cấp | Toàn bài |
| 8 | Nghiên cứu liên quan | literature matrix, DOI/URL, full-text ghi chú, danh mục trích dẫn đã sửa | Đóng góp đối chiếu bằng chứng, không coi các thuật toán đã có là mới | 2, 6 |

## Thứ tự phụ thuộc

- Mục 1 -> mục 2 -> khóa nhãn, chia nhóm -> mục 3 -> mục 4 -> mục 5 -> sửa phần kết luận.
- Mục 6 bắt đầu sớm (kiến trúc) nhưng biểu đồ hiệu năng phải chờ mục 4.
- Mục 7–8 triển khai song song ngay từ đầu.

## Điểm dừng bắt buộc (quality gates)

1. Chưa có nguồn và quyền dùng => không đưa tài liệu vào dữ liệu nghiên cứu.
2. Chưa có nhãn gold được xác nhận => không công bố F1 nghiên cứu.
3. Chưa có file `split_manifest.csv` cố định => không thử nghiệm so sánh chính thức.
4. Có kết quả `dev` nhưng chưa có `test` => chỉ báo cáo thử nghiệm phát triển, không là kết quả cuối.
5. Có E4 oracle nhưng chưa có E5 => không được khẳng định hệ thống đầu-cuối tốt.
6. Chưa được cấp mẫu/nộp cuối => không tuyên bố đã tuân thủ định dạng hội thảo.
