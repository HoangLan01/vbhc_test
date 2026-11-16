# BỘ KHỞI TẠO THỰC NGHIỆM BÀI BÁO SF2026

**Đề tài:** Trích xuất và phân luồng nhiệm vụ từ văn bản hành chính tiếng Việt.

**Tình trạng:** Bộ mã khung có thể chạy; **KHÔNG chứa văn bản thực tế, dữ liệu gán nhãn, kết quả đo, huấn luyện PhoBERT hoặc LLM**. Không sử dụng file ví dụ như kết quả nghiên cứu. Đọc toàn bộ `docs/QUY_TRINH_8_MUC.md` trước khi thao tác.

## 0. Chuẩn bị Ubuntu / WSL / Linux

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip tesseract-ocr tesseract-ocr-vie tesseract-ocr-eng
cd SF2026_Research_Kit
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements-core.txt
python scripts/workflow.py init
```

Chạy trên Windows trực tiếp cũng được bằng `py -m venv .venv` rồi `.venv\\Scripts\\activate` (PowerShell), `py -m pip install ...`; cần cài Tesseract tiếng Việt riêng nếu dùng OCR.

Lệnh kiểm tra:

```bash
python scripts/workflow.py --help
python scripts/workflow.py audit
```

`audit` tạo chứng cứ môi trường và checksum ở `evidence/`, **không phải kết quả nghiên cứu**.

## 1. Dataset thực tế – mục review 1

1. Chỉ sao chép văn bản được phép sử dụng vào `data/raw/` (hỗ trợ DOCX/PDF/TXT/PNG/JPG).
2. Chạy:

```bash
python scripts/workflow.py ingest
```

3. Mở `data/processed/documents_manifest.csv`, điền: `family_id`, `doc_date`, `doc_type`, `source_url_or_archive`, `permission_basis`, `access_level`, `anonymized`.
4. Với trang scan hoặc ảnh, cài OCR rồi chạy `python scripts/workflow.py ingest --ocr --force` **chỉ khi chưa gán nhãn**, vì `--force` ghi đè manifest và đoạn ứng viên. Trước khi chạy phải sao lưu CSV có chỉnh sửa.
5. Kiểm tra thủ công đoạn nguồn; OCR không bảo đảm đúng số, ngày, tên cơ quan, dấu tiếng Việt. `candidate_segments.csv` chỉ là đơn vị đoạn để gán thử; cần tách/ghép lại nếu một đoạn chứa nhiều nhiệm vụ, và giữ định danh ổn định.

**Điều kiện nghiệm thu:** bảng thống kê số văn bản, số đoạn, nguồn hợp lệ, cơ cấu loại văn bản, phân bố văn bản theo năm, tỷ lệ trang cần OCR, mẫu âm tính (không có nhiệm vụ cấp xã). Không ghi “300–500 văn bản đã thu thập” khi chưa có thật.

## 2. Nhãn độc lập – mục review 2

```bash
python scripts/workflow.py prepare-annotations
```

- `data/annotations/segments_gold.csv`: mỗi đoạn ít nhất có `task_present` (0/1), `commune_relevance` (0/1), `annotator_id`, `label_status=approved` sau khi đã đối soát.
- `data/annotations/tasks_gold.csv`: mỗi nhiệm vụ là **một** hàng, có `task_id` duy nhất và `document_id`, `source_location`, `source_text`, `task_text`, vai trò, thời hạn, sản phẩm, phòng chủ trì (`gold_unit`), căn cứ nguồn và căn cứ phân công. Chỉ lấy nhãn phòng từ chức năng/thẩm quyền có xác nhận, **không dùng gợi ý mô hình làm nhãn chuẩn**.
- Để đo độ nhất quán, sao chép template đoạn cho hai người và gán độc lập thành `segments_annotatorA.csv`, `segments_annotatorB.csv`, không tham khảo nhãn của nhau. Lệnh:

```bash
python scripts/workflow.py qc-labels
```

Tạo `results/metrics/annotation_qc.csv` và `results/errors/annotation_conflicts.csv` (nếu có nhãn thật). Kappa phù hợp với nhãn phân loại 0/1; **không** coi nó là chỉ số chất lượng gán span, trích xuất đa trường hoặc nhãn phân luồng khi chưa kiểm tra riêng. Cần giải quyết bất đồng rồi tạo bản `approved`.

## 3. Khóa tập và baseline – mục review 3

`family_id`: dùng cùng mã cho các phiên bản gần trùng / các bản thuộc cùng một chuỗi công văn nếu có rò rỉ nội dung; điền cho **mọi** văn bản. Chạy:

```bash
python scripts/workflow.py validate
python scripts/workflow.py split --seed 42 --test-size 0.15 --dev-size 0.15
```

`split` phân nhóm tài liệu (không chia ngẫu nhiên từng câu) và không ghi đè split đã có. Cần xem phân bố nhãn train/dev/test; nếu quá lệch, phải thiết kế lại split trước khi thử model, lưu lý do và **không đổi sau khi xem kết quả test**.

**Phát hiện/lọc nhiệm vụ với luật đơn giản (E1, E2):**

```bash
python scripts/workflow.py predict-detection --split dev
python scripts/workflow.py evaluate-detection --split dev
```

**Phân luồng E4:** Trước hết điền `config/units.json` bằng tên, chức năng, từ khóa, căn cứ và thời gian hiệu lực của các phòng THỰC. `config/units_EXAMPLE_ONLY.json` chỉ giải thích cú pháp, tuyệt đối không đưa vào nghiên cứu. Các mã `gold_unit` phải khớp `unit_id`.

```bash
python scripts/workflow.py predict-routing --method rule --split dev
python scripts/workflow.py evaluate-routing --method rule --split dev
```

`rule` chỉ là baseline heuristic, không phải quy tắc pháp lý được bảo đảm. Không được suy ra phòng chủ trì chỉ vì thấy một từ khóa.

**Embedding:** cài thêm theo `requirements-ml.txt`, cần Internet **trên máy bạn** khi tải mô hình lần đầu (bộ kit không kèm trọng số):

```bash
pip install -r requirements-ml.txt
python scripts/workflow.py predict-routing --method embedding --split dev
python scripts/workflow.py evaluate-routing --method embedding --split dev
python scripts/workflow.py predict-routing --method hybrid --split dev --alpha 0.75
python scripts/workflow.py evaluate-routing --method hybrid --split dev
```

`hybrid` có hàm điểm thử nghiệm `alpha * sim_embedding + (1-alpha) * từ_khóa`, và lọc theo thời gian hiệu lực hoặc quy tắc loại trừ do con người cung cấp. **Chưa phải mô hình phân luồng chính thức; trọng số 0.75 chỉ là giá trị khởi tạo, phải chọn trên dev.** Nếu không có căn cứ thẩm quyền cho quy tắc loại trừ, không được khai báo quy tắc đó.

Chốt mô hình/ngưỡng trên `dev`, rồi mới chạy `test` (không điều chỉnh sau khi xem test):

```bash
python scripts/workflow.py predict-routing --method rule --split test
python scripts/workflow.py evaluate-routing --method rule --split test
python scripts/workflow.py predict-routing --method embedding --split test
python scripts/workflow.py evaluate-routing --method embedding --split test
python scripts/workflow.py predict-routing --method hybrid --split test --alpha 0.75
python scripts/workflow.py evaluate-routing --method hybrid --split test
```

Lưu log từng lệnh qua `2>&1 | tee evidence/ten_lenh.log` trong Ubuntu. Ghi lại commit/mã phiên bản, tham số, thời gian, máy chạy. Các dự đoán được lưu theo `task_id`, không ghi đè nếu không có `--force`.

**PhoBERT/LLM:** Bộ kit CHƯA có script huấn luyện hai mô hình này. Chỉ bổ sung sau khi có nhãn và baseline đạt chuẩn. PhoBERT cần đầu vào tách từ trước, thiết kế train/dev/test, hyperparameters và seed; LLM cần prompt, JSON schema, revision, nhiệt độ, nguồn tham chiếu, chi phí, và dữ liệu có quyền gửi ra ngoài. Không được viết vào bài là “đã chạy PhoBERT/LLM” khi chưa chạy.

## 4. E1–E5 – mục review 4

- **E1:** phát hiện đoạn có nhiệm vụ – `evaluate-detection` đo P/R/F1 trên đoạn gold.
- **E2:** lọc cấp xã trên đoạn mà gold xác nhận có nhiệm vụ. Đây là E2 đánh giá **oracle đoạn**, không phải end-to-end.
- **E3:** điền `data/annotations/extraction_predictions.csv` từ hệ thống trích xuất thực đã chạy, mỗi dự đoán nối với một `task_id` gold (đo ở điều kiện oracle). Chạy `python scripts/workflow.py evaluate-extraction --split test`. Chỉ số là **Exact Match ở mức trường và bản ghi**, chưa phải Precision/Recall span và chưa phải E5.
- **E4:** `evaluate-routing`: top-1, top-2, macro-F1, coverage (tỷ lệ không từ chối). Các trường hợp từ chối tính **sai** đối với Top-1 toàn bộ tập; phải công bố coverage riêng.
- **E5:** chạy hệ thống thực từ DOCX/PDF/scan, sau đó người kiểm chứng ghép dự đoán hệ thống với mọi nhiệm vụ gold trong `e5_matches.csv`. Chạy `python scripts/workflow.py evaluate-e5 --split test`. Chỉ số sơ bộ dựa trên toàn bộ gold; **chưa tính số task dự đoán thừa (FP)**, cần thống kê thêm FP và phép ghép 1-1 để công bố Precision/F1 end-to-end.

**Không được coi E3 với task_id gold là đánh giá end-to-end.** Cần báo cáo số mẫu từng tác vụ, ma trận nhầm lẫn phòng chủ trì và sai sót theo nguồn PDF/OCR.

## 5. Ví dụ có truy vết – mục review 5

Chọn một hoặc hai văn bản công khai đã nằm trong tập kiểm thử, có quyền dẫn. Báo cáo: ảnh/trích đoạn gốc + trang, gold nhiệm vụ, đầu ra hệ thống, ứng viên phòng và điểm, căn cứ chức năng từ văn bản có hiệu lực, người kiểm tra, sai khác so với gold. Nếu văn bản nhiều đơn vị/thời hạn tách đoạn, ưu tiên minh họa tình huống đó. **Không dùng một ví dụ tự tưởng tượng để chứng minh chất lượng mô hình.**

## 6. Hình 1, 2 – mục review 6

Vẽ bằng PowerPoint, SVG hoặc draw.io (sơ đồ có chữ rõ khi in), xuất PDF vector hoặc PNG 300 DPI đủ kích thước. Tái hiện chính xác pipeline đã triển khai. Không biến prototype thành ảnh “hệ thống hoàn thành”. Hình kết quả chỉ sinh từ `results/metrics/` sau khi thí nghiệm thật.

## 7. Mẫu hội thảo – mục review 7

Lấy template cuối cùng SF2026 do Ban tổ chức/Thầy cung cấp; rà soát số trang, cột, cỡ chữ, hình, chú thích, tài liệu tham khảo, thông tin tác giả, địa chỉ liên hệ, giới hạn dung lượng, định dạng tệp. Mẫu đề cương thạc sĩ PTIT KHÔNG phải mẫu kỷ yếu SF2026.

## 8. Nghiên cứu liên quan – mục review 8

Tạo `docs/LITERATURE_MATRIX.csv` với: trích dẫn đầy đủ, DOI/URL, loại dữ liệu, tác vụ, phương pháp, chỉ số, điểm khác đề tài, tình trạng kiểm chứng. Đối chiếu IE cấp tài liệu, Vietnamese administrative IE, PhoBERT, structured LLM và routing có ràng buộc chức năng. Không trích dẫn bài chưa đọc/không xác thực. Nếu bổ sung tài liệu phải cập nhật trích dẫn trong nội dung theo thứ tự, giữ tính nhất quán.

## Quy định báo cáo học thuật

1. Không được thay ô trống bằng số tưởng tượng hoặc chạy code trên nhãn giả rồi mô tả như dữ liệu hành chính thật.
2. Chỉ chạy test sau khi cố định phương pháp/ngưỡng bằng train/dev.
3. Kết quả phải truy ngược tới `document_id`, `task_id`/`segment_id`, nhãn gold, dự đoán, model version và log.
4. Không công bố thông tin cá nhân hoặc dữ liệu công vụ không được phép.
5. Số liệu `E1–E5` phải phân biệt chính xác cấp đánh giá: đoạn, nhiệm vụ chuẩn, bản ghi hoàn chỉnh và toàn quy trình.

## Tài liệu đi kèm

- `docs/QUY_TRINH_8_MUC.md`: checklist chi tiết + cột nghiệm thu.
- `docs/ANNOTATION_GUIDE.md`: quy tắc gán nhãn thử nghiệm.
- `docs/REVIEW_RESPONSE_TEMPLATE.md`: khung phản hồi reviewer.
- `config/units.json`: file trống cần điền theo cơ cấu có hiệu lực.
- `scripts/workflow.py`: công cụ ingest, QC, group split, baseline, metric và audit.
