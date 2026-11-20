# Cách đưa bối cảnh ChatGPT sang Codex trong VS Code

**Mục đích:** Codex không tự đọc toàn bộ cuộc hội thoại ChatGPT, nên cần các file bàn giao trong project.

## Cài vào dự án đã có (Windows)

1. Giải nén ZIP này **vào chính thư mục** `D:\2025\src\SF2026_Research_Kit`, để `AGENTS.md` nằm cùng cấp với `README.md`, `scripts/` và `data/`.
2. Giữ nguyên các thư mục hiện có. Gói này chỉ thêm `AGENTS.md`, `README_CACH_BAN_GIAO_CODEX.md` và các tệp `docs/CODEX_*.md` / `docs/CODEX_START_PROMPT.txt`; không cần thay `scripts/workflow.py` hoặc dữ liệu.
3. Trong VS Code, mở toàn bộ thư mục dự án (File > Open Folder), không chỉ mở file Python riêng.
4. Mở bảng Codex (biểu tượng Codex; nếu ẩn: Ctrl+Shift+P -> `Codex: Open Codex Sidebar`). Bắt đầu **cuộc chat Codex mới** để các hướng dẫn `AGENTS.md` được nạp từ đầu phiên.
5. Mở `docs/CODEX_START_PROMPT.txt`, sao chép nội dung và dán vào Codex; cũng có thể thêm `AGENTS.md` và các tài liệu context vào prompt nếu cần.
6. Yêu cầu đầu tiên của Codex phải là **chỉ đọc/audit**, không chỉnh file, không chạy `--force`. Sau khi xem báo cáo đầu tiên mới giao công việc code từng bước.

## Kiểm tra đã đặt file đúng nơi

Tại PowerShell trong thư mục dự án:

```powershell
Test-Path .\AGENTS.md
Test-Path .\docs\CODEX_PROJECT_CONTEXT.md
Test-Path .\docs\CODEX_CURRENT_STATUS.md
Test-Path .\docs\CODEX_NEXT_ACTION.md
```

Cả bốn lệnh phải trả về `True`.

## Cập nhật tiến độ lâu dài

- Sau mỗi buổi làm việc, nhờ Codex cập nhật **tình trạng được xác minh** trong `docs/CODEX_CURRENT_STATUS.md` và bước tiếp theo trong `docs/CODEX_NEXT_ACTION.md`.
- **Không** biến suy luận/giá trị giả thành kết quả đã xác nhận; khi có kết quả thật phải ghi đường dẫn evidence, metrics, prediction, cấu hình, ngày chạy.
- Khi cần trao đổi lại ở ChatGPT, gửi các tệp context/status mới và log nếu có; ChatGPT không tự thấy những thay đổi trên ổ D:.
- Nếu muốn Codex đọc đầy đủ phản biện và bài báo, sao chép file review và bài báo gốc/vòng 1 vào `paper/` rồi yêu cầu Codex đọc. Đừng đưa nội dung nhạy cảm lên cloud khi chưa được phép.
