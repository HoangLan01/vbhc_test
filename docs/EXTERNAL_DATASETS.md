# Bộ dữ liệu ngoài dùng trong SF2026

Hai bộ dữ liệu dưới đây được lưu riêng trong `data/external/`. Chúng không phải dữ liệu mục tiêu của UBND cấp xã, không thay thế `segments_gold.csv` hoặc `tasks_gold.csv`, và không được trộn vào test E1–E5 nội bộ.

## OTA dataset

- Kho: `tedbelford/OTA-dataset`.
- Revision đã pin: `42196fc627aa0c3070d843a6868970ad0d72a2cc`.
- Giấy phép ghi trên dataset card: MIT.
- Quy mô công bố trên card: 1.409 PDF, 5.812 trang và 18.359 cặp Organization–Task duy nhất.
- Kiểm kê revision đã pin trong workspace: 1.409 PDF ghép đủ 1.409 JSON, 18.730 entry và 18.614 cặp exact-unique; không có JSON lỗi hoặc entry sai schema. Các thí nghiệm phải dùng số kiểm kê theo revision và nêu sai khác với dataset card.
- Phạm vi: văn bản chỉ thị từ VBPL, giai đoạn 1955–2015.
- Vai trò trong đề tài: dữ liệu ngoài để huấn luyện chuyển giao/đối chứng E3 cho quan hệ đơn vị–nhiệm vụ và kiểm tra grounding nguồn.
- Giới hạn: không có nhãn `commune_relevance`, `gold_unit` nội bộ, routing theo cơ cấu hiện hành hoặc test E5 của corpus mục tiêu. Dataset viewer trên Hugging Face hiện lỗi sinh dữ liệu; dự án tải ZIP đã pin revision và tự kiểm tra cấu trúc/hash.

Nguồn: https://huggingface.co/datasets/tedbelford/OTA-dataset

## PAP NER

- Kho: `Leekien0108/PAP_NER`.
- Revision đã pin: `7a0f6b1233667702925baa69c07c55d5d26eb6cd`.
- Giấy phép: CC BY 4.0.
- Quy mô công bố: 162.801 câu, 205.807 thực thể, năm loại nhãn BIO.
- Nhãn: `CQ` cơ quan, `VBPL` văn bản pháp lý, `ĐT` đối tượng, `NG` thời gian và `SL` số lượng.
- Schema thực tế trên Hugging Face có năm cột mỗi token, trong khi dataset card mô tả bốn cột. Pipeline chỉ dùng cột thứ tư làm nhãn NER BIO và kiểm kê riêng cột thứ năm; không diễn giải cột phụ thành nhãn nghiên cứu khi chưa có mô tả từ nguồn gốc.
- Vai trò trong đề tài: tiền huấn luyện token classification cho E3, sau đó fine-tune lại trên span gold của corpus mục tiêu.
- Giới hạn: không có span nhiệm vụ, vai trò chủ trì/phối hợp, sản phẩm, liên kết task hoặc phòng chủ trì nội bộ. Điểm số từ bài PAP_NER không phải kết quả của SF2026.

Nguồn: https://huggingface.co/datasets/Leekien0108/PAP_NER

Trích dẫn gốc PAP_NER:

> Dinh-Dien La, Tien-Bang Tran, Ngoc-Huy Du, Ngoc-Hung Dang, Trung-Nghia Phung, and Van-Khanh Tran. PAP_NER: A large-scale vietnamese administrative named entity recognition corpus and hybrid deep learning architecture. PLOS ONE, 21(7): e0353166, 2026. DOI: 10.1371/journal.pone.0353166.

## Lệnh quản lý

Tải cả hai bộ và giải nén OTA an toàn:

```powershell
.\.venv\Scripts\python.exe scripts\external_datasets.py fetch --dataset all --extract-ota
```

Kiểm kê lại mà không tải:

```powershell
.\.venv\Scripts\python.exe scripts\external_datasets.py inspect --dataset all
```

Chuẩn hóa thành JSONL dùng cho pipeline huấn luyện chuyển giao:

```powershell
.\.venv\Scripts\python.exe scripts\external_datasets.py prepare --dataset all
```

Đầu ra gồm `ota/prepared/ota_documents.jsonl`, `ota/prepared/ota_pairs.jsonl` và ba split `pap_ner/prepared/{train,dev,test}.jsonl`. Mọi bản ghi đều có `research_status` chỉ rõ đây là dữ liệu ngoài, không phải target gold.

## Fine-tune PhoBERT trên PAP_NER

Kiểm tra kỹ thuật trên CPU với tập con nhỏ:

```powershell
.\.venv\Scripts\python.exe scripts\train_pap_ner.py --smoke
```

Full run chỉ nên thực hiện trên máy có CUDA:

```powershell
.\.venv\Scripts\python.exe scripts\train_pap_ner.py `
  --epochs 3 `
  --train-batch-size 8 `
  --gradient-accumulation-steps 2 `
  --seed 42
```

Kết quả PAP_NER phải ghi là external benchmark/transfer learning. Không đưa F1 này vào E1–E5 của corpus mục tiêu. OTA không có BIO span; OTA sẽ được dùng cho bộ phân loại/kiểm chứng cặp Organization–Task với negative sampling tách theo tài liệu, không được mô tả như mô hình trích xuất đầu-cuối.

Kiểm tra file/hash đã tải:

```powershell
.\.venv\Scripts\python.exe scripts\external_datasets.py status --dataset all
```

Kết quả kiểm kê và checksum cục bộ được lưu tại `data/external/external_manifest.json`.
