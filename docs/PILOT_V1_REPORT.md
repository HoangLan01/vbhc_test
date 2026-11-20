# Báo cáo khóa pilot v1

Ngày khóa: 19/11/2026. Đây là báo cáo quy trình và nhãn pilot, không phải kết quả E1–E5.

## Phạm vi

- 80 mẫu pilot từ 17 văn bản ban đầu.
- Hai người gán độc lập trên cùng danh sách unit ứng viên.
- Nhãn: `task_present` và `commune_relevance`.
- A/B không xem gợi ý máy hoặc nhãn của nhau trong quá trình gán.

## QC trước adjudication

| Trường | n | Raw agreement | Cohen's Kappa | Bất đồng theo trường |
|---|---:|---:|---:|---:|
| `task_present` | 80 | 0,8875 | 0,6842 | 9 |
| `commune_relevance` | 80 | 0,8750 | 0,6429 | 10 |

- 19 dòng bất đồng theo trường trên 10 segment duy nhất.
- 9/10 segment bất đồng ở cả hai trường.
- Kappa chỉ phản ánh hai nhãn phân loại pilot; không đo span, tách nhiệm vụ hoặc routing.

## Adjudication và sửa đơn vị

- Queue bắt buộc: 16 segment, là hợp của bất đồng và ghi chú lỗi cấu trúc.
- 15 segment được xác nhận là unit hợp lệ.
- Một segment bị chia vụn được ghép từ `S0111–S0114` trên trang 7, block 6–9.
- Đơn vị ghép được người adjudicator xác nhận nhãn `1/1`.
- Mọi quyết định adjudication có lý do; mapping giữ đầy đủ segment gốc.

## Pilot approved

| Nhãn | Số unit |
|---|---:|
| `0/0` | 55 |
| `1/0` | 1 |
| `1/1` | 24 |
| **Tổng** | **80** |

Nguồn khóa:

- `data/annotations/pilot_units_approved.csv`
- `data/annotations/pilot_unit_mapping.csv`
- `evidence/pilot_freezes/pilot_v1_20261119_074050_542202/freeze_manifest.json`

`approved_pilot` không phải gold toàn corpus. Pilot ban đầu được chọn cân bằng tín hiệu heuristic nên phân bố trên không được diễn giải là tỷ lệ nhiệm vụ của toàn bộ 79 văn bản.

## Bài học phương pháp

1. Block PDF có thể chỉ dài một từ và không phải đơn vị ngôn ngữ.
2. Ngữ cảnh toàn văn cần cho `commune_relevance`, nhưng không được dùng để biến một block không có nhiệm vụ thành positive.
3. `member_segment_ids` chỉ dùng để ghép text, không dùng như danh sách dẫn chiếu ngữ cảnh.
4. Unit ghép phải được gán lại sau khi xem nội dung hoàn chỉnh.
5. Lô mở rộng phải được tạo trên annotation units ổn định, không lấy trực tiếp toàn bộ block thô.
