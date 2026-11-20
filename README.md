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

### Bộ dữ liệu ngoài

OTA và PAP_NER được quản lý riêng dưới `data/external/`, không trộn vào corpus mục tiêu hoặc gold/test E1–E5. Tải bản đã pin revision và kiểm tra hash bằng:

```powershell
.\.venv\Scripts\python.exe scripts\external_datasets.py fetch --dataset all --extract-ota
```

OTA được dùng cho chuyển giao/đối chứng trích xuất quan hệ đơn vị–nhiệm vụ; PAP_NER được dùng để tiền huấn luyện token classification cho E3. Xem phạm vi, giấy phép và giới hạn tại `docs/EXTERNAL_DATASETS.md`.

Sau khi tải, chuẩn hóa thành JSONL huấn luyện ngoài bằng:

```powershell
.\.venv\Scripts\python.exe scripts\external_datasets.py prepare --dataset all
```

Các file chuẩn hóa vẫn mang cờ external/non-gold và không được ghép vào test của corpus mục tiêu.

Smoke test fine-tune PhoBERT/PAP_NER trên CPU:

```powershell
.\.venv\Scripts\python.exe scripts\train_pap_ner.py --smoke
```

Full fine-tune cần GPU CUDA; script từ chối chạy full trên CPU nếu không có `--allow-cpu-full`. Metric PAP_NER là external benchmark, không phải kết quả E1–E5 nội bộ.

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

### 1.1. Bổ sung văn bản theo cơ chế incremental

Sau lần ingest đầu tiên, sao chép tài liệu mới vào `data/raw/` rồi chạy trên Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe scripts\workflow.py ingest --incremental
```

Nếu tài liệu mới là ảnh hoặc có trang scan cần OCR:

```powershell
.\.venv\Scripts\python.exe scripts\workflow.py ingest --incremental --ocr
```

Cơ chế này:

- đối chiếu SHA-256 nên nhận ra tài liệu đã nhập kể cả khi file bị đổi tên;
- chỉ nối thêm tài liệu và đoạn mới, giữ nguyên metadata, `document_id`, `segment_id` và `source_location` cũ;
- cảnh báo rồi bỏ qua nếu một đường dẫn cũ có nội dung/hash mới;
- không cho kết hợp `--incremental` với `--force`;
- nếu `segments_gold.csv` đã có hàng nhãn, chỉ nối các đoạn mới với cột nhãn trống; nếu file gold còn rỗng thì giữ nguyên file rỗng;
- ghi nhật ký từng lần chạy tại `evidence/ingest_incremental_*.json`;
- có thể chạy lặp lại: tài liệu đã có sẽ bị bỏ qua và không tạo hàng trùng.

Sau mỗi lần bổ sung, kiểm tra manifest và điền metadata cho tài liệu mới. Không dùng incremental để thay thế hoặc cập nhật một văn bản cũ đã thay đổi nội dung; trường hợp đó cần được xem như phiên bản mới và xử lý có chủ đích.

### 1.2. Báo cáo QC và chọn lô gán nhãn thử

Trên Windows PowerShell, chạy báo cáo dẫn xuất không sửa manifest, đoạn ứng viên hoặc tài liệu gốc:

```powershell
.\.venv\Scripts\python.exe scripts\workflow.py quality-report
```

Đầu ra nằm trong `results/quality/`: thống kê tổng hợp, thống kê theo tài liệu và trạng thái từng trang PDF. Báo cáo chỉ chứa số đếm/vị trí, không chép toàn văn đoạn nguồn. Lệnh không ghi đè đầu ra đã tồn tại nếu không có `--force`.

Chọn pilot mặc định 80 đoạn, seed 42, tối thiểu 3 đoạn từ mỗi văn bản:

```powershell
.\.venv\Scripts\python.exe scripts\workflow.py sample-pilot --n 80 --seed 42 --min-per-document 3
```

- `data/annotations/pilot_segments.csv`: file kiểm toán cách chọn mẫu, có tín hiệu heuristic nhưng **không phải nhãn gold**.
- `data/annotations/segments_annotatorA.csv` và `segments_annotatorB.csv`: cùng danh sách `segment_id`, mọi cột nhãn để trống và không chứa tín hiệu heuristic.
- `results/quality/pilot_selection_summary.csv`: phân bố lô pilot.

Không dùng file master để gán nhãn vì có thể làm người gán bị ảnh hưởng bởi tín hiệu chọn mẫu. Hai người gán dùng riêng biểu A/B và không xem nhãn của nhau.

Nếu cần gợi ý máy để rà soát **sau khi** người gán đã làm độc lập, chạy:

```powershell
.\.venv\Scripts\python.exe scripts\workflow.py suggest-pilot-labels
```

Lệnh tạo `data/annotations/segments_ai_suggestions.csv` bằng luật/từ khóa cục bộ, không gửi dữ liệu ra ngoài và không sửa biểu A/B. Mọi hàng đều mang trạng thái `NON_GOLD_AI_SUGGESTION` và `human_review_required=1`. Không dùng file này để tính Kappa, huấn luyện như gold hoặc báo cáo chỉ số nghiên cứu khi chưa có người xác nhận.

### 1.3. Giao diện gán nhãn cục bộ trên Windows

Người A chạy:

```powershell
.\.venv\Scripts\python.exe scripts\annotate_segments.py `
  --input data/annotations/segments_annotatorA.csv `
  --annotator-id A01
```

Người B chạy riêng:

```powershell
.\.venv\Scripts\python.exe scripts\annotate_segments.py `
  --input data/annotations/segments_annotatorB.csv `
  --annotator-id B01
```

Ứng dụng hiển thị đoạn trước, đoạn đang gán và đoạn sau trong cùng văn bản; không đọc hoặc hiển thị file gợi ý máy. Phím tắt chi tiết: `F1` task=0, `F2` task=1, `F3` commune=0, `F4` commune=1, `PageUp` quay lại, `PageDown` lưu và sang đoạn tiếp theo, `Ctrl+S` lưu. Ba phím một-chạm giúp giảm thao tác nhưng không dùng AI: `F5` = không có nhiệm vụ, `F6` = có nhiệm vụ nhưng không thuộc cấp xã, `F7` = có nhiệm vụ thuộc cấp xã; cả ba đều lưu và chuyển sang hàng kế tiếp. Khi `task_present=0`, ứng dụng tự đặt `commune_relevance=0`.

Mỗi phiên tạo bản sao tại `evidence/annotation_backups/`, khóa file để tránh hai tiến trình sửa cùng lúc và chỉ lưu `label_status=draft`. Nhật ký append-only ở `evidence/annotation_audit/` chỉ giữ ID, nhãn, hash và thời gian; không chép toàn văn hoặc nội dung ghi chú. Kiểm tra file và tiến độ mà không mở giao diện:

```powershell
.\.venv\Scripts\python.exe scripts\annotate_segments.py `
  --input data/annotations/segments_annotatorA.csv `
  --annotator-id A01 `
  --check
```

### 1.4. Adjudication pilot sau QC

Sau khi cả A/B hoàn thành và `qc-labels` đã tạo danh sách bất đồng, kiểm tra hàng đợi bắt buộc mà chưa ghi file:

```powershell
.\.venv\Scripts\python.exe scripts\adjudicate_pilot.py --check --mode mandatory
```

Mở giao diện adjudication:

```powershell
.\.venv\Scripts\python.exe scripts\adjudicate_pilot.py `
  --mode mandatory `
  --adjudicator-id ADJ01
```

Tool hiển thị nhãn/ghi chú A và B, ngữ cảnh ±3 segment và toàn văn cùng `document_id`; segment hiện tại được làm nổi bật. `F5/F6/F7` chốt đơn vị hợp lệ lần lượt thành `0/0`, `1/0`, `1/1`; `F8` đánh dấu cần ghép và yêu cầu liệt kê `member_segment_ids` cùng tài liệu. Các trạng thái khác gồm `needs_source_check`, `ocr_error`, `exclude_invalid_unit`.

Lần mở đầu tiên tạo `data/annotations/pilot_adjudication.csv` và manifest khóa SHA-256 của A/B, context và conflicts. Mỗi phiên có backup/audit. Kết quả vẫn là `PILOT_ADJUDICATION_NOT_GOLD`; tool không sửa `segments_gold.csv`.

### 1.5. Tạo đơn vị pilot dẫn xuất sau adjudication

Giữ nguyên mọi `segment_id` gốc và tạo annotation unit/mapping riêng:

```powershell
.\.venv\Scripts\python.exe scripts\build_pilot_units.py prepare
.\.venv\Scripts\python.exe scripts\build_pilot_units.py check
```

Đầu ra:

- `data/annotations/pilot_annotation_units.csv`: text đơn vị dẫn xuất và nhãn draft;
- `data/annotations/pilot_unit_mapping.csv`: ánh xạ unit về từng `segment_id` gốc;
- `data/annotations/pilot_units_manifest.json`: hash nguồn và thông tin provenance.

Đơn vị `needs_merge` được ghép theo đúng thứ tự `member_segment_ids` nhưng để nhãn trống. Sau khi người adjudicator đọc text ghép và đối chiếu nguồn, chốt nhãn bằng:

```powershell
.\.venv\Scripts\python.exe scripts\build_pilot_units.py label `
  --unit-id PILOT_MERGE_... `
  --task-present 1 `
  --commune-relevance 1 `
  --adjudicator-id ADJ01 `
  --rationale "Lý do chốt nhãn sau khi xem đơn vị ghép"
```

Lệnh tạo backup và audit, chỉ sửa file units dẫn xuất; kết quả vẫn chưa phải gold cho đến bước nghiệm thu riêng.

### 1.6. Khóa pilot v1

Khi mọi unit đã có nhãn và không còn pending, tạo bản approved riêng cùng snapshot SHA-256:

```powershell
.\.venv\Scripts\python.exe scripts\freeze_pilot.py `
  --approval-id pilot_v1 `
  --approved-by ADJ01
```

Lệnh không sửa A/B, adjudication, mapping hoặc `segments_gold.csv`; không ghi đè bản approved/snapshot đã tồn tại. `approved_pilot` chỉ xác nhận pilot và quy trình, không phải gold toàn corpus. Xem `docs/PILOT_V1_REPORT.md` và `docs/GOLD_EXPANSION_PLAN.md`.

### 1.7. Proposal mở rộng gold và review metadata

Tạo unit proposals toàn corpus, mapping, readiness và gợi ý family mà không sửa nguồn:

```powershell
.\.venv\Scripts\python.exe scripts\prepare_gold_expansion.py
```

Sau khi manifest metadata thay đổi, refresh có backup output cũ:

```powershell
.\.venv\Scripts\python.exe scripts\prepare_gold_expansion.py --refresh
```

Các unit mới luôn mang trạng thái non-gold. Block ngắn chỉ được gắn cờ `needs_segmentation_review`, không tự ghép. Family pairs là gợi ý heuristic phải do người duyệt xác nhận.

Tạo biểu metadata 79 văn bản có sẵn các giá trị hiện tại, ngày đã xác minh và gợi ý family:

```powershell
.\.venv\Scripts\python.exe scripts\review_manifest_metadata.py prepare
.\.venv\Scripts\python.exe scripts\review_manifest_metadata.py check
```

Mở giao diện nhập/review metadata:

```powershell
.\.venv\Scripts\python.exe scripts\review_manifest_metadata.py gui
```

Có thể điền trước các trường lặp lại và family/source ổn định vào trạng thái `needs_review`:

```powershell
.\.venv\Scripts\python.exe scripts\review_manifest_metadata.py autofill
```

`autofill` tạo backup, không tự approve và không áp dụng vào manifest. Ngày không có chứng cứ xác minh vẫn để trống.

GUI có `Approve & Next`, nhảy tới hàng chưa approved và nút sao chép `permission_basis`/`access_level`/`anonymized`/`reviewer_id` từ hàng vừa lưu. Nó không tự sao chép `family_id`, nguồn hoặc ngày vì các trường này phải xác nhận theo từng tài liệu.

Điền `family_id`, `doc_date`, `source_url_or_archive`, `permission_basis`, `access_level`, `anonymized`, `reviewer_id`; chỉ đặt `review_status=approved` sau khi kiểm tra đủ căn cứ. Áp dụng các hàng approved bằng:

```powershell
.\.venv\Scripts\python.exe scripts\review_manifest_metadata.py apply
```

Lệnh apply bảo vệ `document_id`/filename/SHA-256, backup manifest và chỉ cập nhật các trường metadata được phép.

### 1.8. Batch gold mở rộng 01 trên annotation units

Sau khi metadata và G0 đạt quality gate, chọn batch 240 unit có seed cố định:

```powershell
.\.venv\Scripts\python.exe scripts\sample_gold_units.py
```

Đầu ra gồm master có đặc trưng audit, hai biểu A/B nhãn trống, summary và batch manifest. Master/heuristic không được đưa cho người gán.

Người A:

```powershell
.\.venv\Scripts\python.exe scripts\annotate_units.py `
  --input data/annotations/gold_batch_01_annotatorA.csv `
  --annotator-id A02
```

Người B dùng file `gold_batch_01_annotatorB.csv` và mã `B02`. GUI hiển thị unit hiện tại, ±3 unit và toàn văn cùng tài liệu; `F5/F6/F7` lần lượt là `0/0`, `1/0`, `1/1`. Không hiển thị master, heuristic hoặc suggestion.

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

### Review phân luồng có truy vết

Sau khi có prediction E4 và `config/units.json` đã được xác nhận, tạo một file review mới mà không sửa prediction hoặc `tasks_gold.csv`:

```powershell
.\.venv\Scripts\python.exe scripts\review_routing.py prepare `
  --predictions results/predictions/routing_hybrid_dev.csv `
  --tasks data/annotations/tasks_gold.csv `
  --units config/units.json `
  --output data/annotations/routing_review_hybrid_dev.csv
```

Ghi một quyết định của người duyệt:

```powershell
.\.venv\Scripts\python.exe scripts\review_routing.py record `
  --review data/annotations/routing_review_hybrid_dev.csv `
  --units config/units.json `
  --task-id TASK_ID `
  --decision accept `
  --reviewer-id R01 `
  --evidence-unit "Căn cứ chức năng/thẩm quyền đã kiểm tra"
```

Các quyết định hỗ trợ: `accept`, `reroute`, `abstain`, `needs_review`, `out_of_scope`. File review luôn mang trạng thái draft/non-gold; chỉ quy trình adjudication riêng mới được phép cập nhật `gold_unit`. Audit chỉ lưu ID/trạng thái/hash, không chép nội dung nhiệm vụ hoặc căn cứ chi tiết.

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
