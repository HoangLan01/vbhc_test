#!/usr/bin/env python3
"""Giao diện gán nhãn đoạn cục bộ cho hai người gán độc lập.

Ứng dụng chỉ mở các file segments_annotator*.csv, không mở gold và không hiển
thị gợi ý máy. Mọi lần lưu đều ghi qua file tạm rồi thay thế nguyên tử.
"""

import argparse
import csv
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_COLUMNS = [
    'document_id',
    'segment_id',
    'source_location',
    'segment_text',
    'task_present',
    'commune_relevance',
    'annotator_id',
    'label_status',
    'notes',
]
CONTEXT_COLUMNS = ['document_id', 'segment_id', 'source_location', 'segment_text']
QUICK_LABELS = {
    'negative': ('0', '0'),
    'task_not_commune': ('1', '0'),
    'task_commune': ('1', '1'),
}


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def read_csv_rows(path):
    if not path.is_file():
        raise ValueError(f'Không tìm thấy file: {path}')
    with path.open('r', newline='', encoding='utf-8-sig') as stream:
        reader = csv.DictReader(stream)
        headers = reader.fieldnames or []
        rows = list(reader)
    return headers, rows


def validate_annotation_file(path, headers, rows):
    name = path.name.lower()
    if not name.startswith('segments_annotator') or not name.endswith('.csv'):
        raise ValueError('Chỉ được mở file segments_annotator*.csv; không mở gold hoặc file gợi ý máy.')
    missing = [column for column in REQUIRED_COLUMNS if column not in headers]
    if missing:
        raise ValueError(f'File gán nhãn thiếu cột: {", ".join(missing)}')
    segment_ids = [row['segment_id'] for row in rows]
    if any(not value.strip() for value in segment_ids):
        raise ValueError('Có segment_id trống.')
    if len(segment_ids) != len(set(segment_ids)):
        raise ValueError('Có segment_id trùng trong file gán nhãn.')
    for row_number, row in enumerate(rows, 2):
        for column in ('task_present', 'commune_relevance'):
            if row[column] not in ('', '0', '1'):
                raise ValueError(f'Dòng {row_number}: {column} phải trống, 0 hoặc 1.')
        if row['task_present'] == '0' and row['commune_relevance'] == '1':
            raise ValueError(f'Dòng {row_number}: task_present=0 không thể có commune_relevance=1.')


def validate_context(headers, rows):
    missing = [column for column in CONTEXT_COLUMNS if column not in headers]
    if missing:
        raise ValueError(f'File ngữ cảnh thiếu cột: {", ".join(missing)}')
    ids = [row['segment_id'] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError('File ngữ cảnh có segment_id trùng.')


def write_csv_atomic(path, headers, rows):
    token = f'{os.getpid()}_{datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")}'
    temp = path.with_name(f'.{path.name}.{token}.tmp')
    try:
        with temp.open('w', newline='', encoding='utf-8-sig') as stream:
            writer = csv.DictWriter(stream, fieldnames=headers, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def append_audit_event(path, payload):
    """Ghi audit append-only, không lưu toàn văn hoặc nội dung ghi chú."""
    path.parent.mkdir(parents=True, exist_ok=True)
    safe_payload = dict(payload)
    forbidden = {'segment_text', 'source_text', 'task_text', 'notes'}
    leaked = forbidden.intersection(safe_payload)
    if leaked:
        raise ValueError(f'Audit không được chứa trường nhạy cảm: {", ".join(sorted(leaked))}')
    with path.open('a', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(safe_payload, ensure_ascii=False, separators=(',', ':')) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


def create_session_backup(path, backup_root):
    backup_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
    destination = backup_root / f'{path.stem}_{stamp}{path.suffix}'
    shutil.copy2(path, destination)
    if sha256(path) != sha256(destination):
        destination.unlink(missing_ok=True)
        raise ValueError('Hash bản sao lưu không khớp file gốc.')
    return destination


def acquire_lock(path, force_unlock=False):
    lock_path = path.with_name(f'.{path.name}.lock')
    if force_unlock and lock_path.exists():
        lock_path.unlink()
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise ValueError(
            f'File đang được một phiên khác sử dụng hoặc còn lock cũ: {lock_path}. '
            'Đóng phiên trước; chỉ dùng --force-unlock khi chắc chắn không còn ứng dụng đang gán.'
        ) from exc
    os.write(descriptor, f'pid={os.getpid()}\nutc={datetime.now(timezone.utc).isoformat()}\n'.encode('utf-8'))
    os.close(descriptor)
    return lock_path


def release_lock(lock_path):
    if lock_path and lock_path.exists():
        lock_path.unlink()


def apply_labels(row, task_present, commune_relevance, annotator_id, notes):
    if task_present not in ('', '0', '1'):
        raise ValueError('task_present phải trống, 0 hoặc 1.')
    if task_present == '0':
        commune_relevance = '0'
    if commune_relevance not in ('', '0', '1'):
        raise ValueError('commune_relevance phải trống, 0 hoặc 1.')
    if task_present == '0' and commune_relevance == '1':
        raise ValueError('task_present=0 không thể có commune_relevance=1.')
    row['task_present'] = task_present
    row['commune_relevance'] = commune_relevance
    row['annotator_id'] = annotator_id.strip() if task_present and commune_relevance else ''
    row['label_status'] = 'draft' if task_present and commune_relevance and annotator_id.strip() else ''
    row['notes'] = notes.strip()
    return row


def apply_quick_label(row, choice, annotator_id, notes=''):
    """Áp dụng một trong ba tổ hợp hợp lệ; chỉ là thao tác nhanh, không phải gợi ý máy."""
    if choice not in QUICK_LABELS:
        raise ValueError(f'Lựa chọn nhanh không hợp lệ: {choice}')
    task_present, commune_relevance = QUICK_LABELS[choice]
    return apply_labels(row, task_present, commune_relevance, annotator_id, notes)


def is_complete(row):
    return (
        row.get('task_present') in ('0', '1')
        and row.get('commune_relevance') in ('0', '1')
        and bool(row.get('annotator_id', '').strip())
        and row.get('label_status') == 'draft'
    )


def progress(rows):
    completed = sum(is_complete(row) for row in rows)
    return completed, len(rows)


def build_context_map(context_rows):
    by_document = {}
    for row in context_rows:
        by_document.setdefault(row['document_id'], []).append(row)
    result = {}
    for document_rows in by_document.values():
        for index, row in enumerate(document_rows):
            result[row['segment_id']] = dict(
                previous=document_rows[index - 1] if index > 0 else None,
                current=row,
                next=document_rows[index + 1] if index + 1 < len(document_rows) else None,
            )
    return result


def check_only(input_path, context_path):
    headers, rows = read_csv_rows(input_path)
    validate_annotation_file(input_path, headers, rows)
    context_headers, context_rows = read_csv_rows(context_path)
    validate_context(context_headers, context_rows)
    context_ids = {row['segment_id'] for row in context_rows}
    missing_context = [row['segment_id'] for row in rows if row['segment_id'] not in context_ids]
    completed, total = progress(rows)
    print(f'File hợp lệ: {input_path}')
    print(f'Tiến độ: {completed}/{total}; thiếu ngữ cảnh: {len(missing_context)}')
    return 0 if not missing_context else 1


class AnnotationApp:
    def __init__(
        self,
        root,
        input_path,
        headers,
        rows,
        context_map,
        annotator_id,
        backup_path,
        lock_path,
        audit_path,
        session_id,
    ):
        import tkinter as tk
        from tkinter import messagebox
        from tkinter.scrolledtext import ScrolledText

        self.tk = tk
        self.messagebox = messagebox
        self.root = root
        self.input_path = input_path
        self.headers = headers
        self.rows = rows
        self.context_map = context_map
        self.annotator_id = annotator_id
        self.backup_path = backup_path
        self.lock_path = lock_path
        self.audit_path = audit_path
        self.session_id = session_id
        self.index = self.first_incomplete_index()
        self.dirty = False

        root.title(f'Gán nhãn SF2026 - {input_path.name} - {annotator_id}')
        root.geometry('1180x820')
        root.minsize(900, 650)
        root.protocol('WM_DELETE_WINDOW', self.on_close)

        self.status_var = tk.StringVar()
        self.location_var = tk.StringVar()
        self.task_var = tk.StringVar()
        self.commune_var = tk.StringVar()

        header = tk.Frame(root, padx=10, pady=8)
        header.pack(fill='x')
        tk.Label(header, textvariable=self.status_var, font=('Segoe UI', 11, 'bold')).pack(side='left')
        tk.Label(header, textvariable=self.location_var, font=('Segoe UI', 10)).pack(side='right')

        context_frame = tk.Frame(root, padx=10)
        context_frame.pack(fill='both', expand=True)
        self.previous_text = self.make_text_panel(context_frame, 'Đoạn trước', 4, '#f1f1f1')
        self.current_text = self.make_text_panel(context_frame, 'Đoạn đang gán', 10, '#fffbe6')
        self.next_text = self.make_text_panel(context_frame, 'Đoạn sau', 4, '#f1f1f1')

        controls = tk.Frame(root, padx=10, pady=8)
        controls.pack(fill='x')
        task_box = tk.LabelFrame(controls, text='Có nhiệm vụ?', padx=8, pady=6)
        task_box.pack(side='left', padx=(0, 10))
        for text, value in [('Chưa chọn', ''), ('Không - F1', '0'), ('Có - F2', '1')]:
            tk.Radiobutton(task_box, text=text, variable=self.task_var, value=value, command=self.on_task_change).pack(side='left')

        commune_box = tk.LabelFrame(controls, text='Liên quan trách nhiệm cấp xã?', padx=8, pady=6)
        commune_box.pack(side='left')
        for text, value in [('Chưa chọn', ''), ('Không - F3', '0'), ('Có - F4', '1')]:
            tk.Radiobutton(commune_box, text=text, variable=self.commune_var, value=value, command=self.mark_dirty).pack(side='left')

        notes_frame = tk.LabelFrame(root, text='Ghi chú trường hợp khó', padx=10, pady=6)
        notes_frame.pack(fill='x', padx=10, pady=(0, 8))
        self.notes_text = ScrolledText(notes_frame, height=3, wrap='word', font=('Segoe UI', 10))
        self.notes_text.pack(fill='x')
        self.notes_text.bind('<<Modified>>', self.on_notes_modified)

        navigation = tk.Frame(root, padx=10, pady=8)
        navigation.pack(fill='x')
        tk.Button(navigation, text='← Trước (PgUp)', command=self.previous).pack(side='left')
        tk.Button(navigation, text='Đoạn chưa gán tiếp theo', command=self.next_incomplete).pack(side='left', padx=8)
        tk.Button(navigation, text='Lưu (Ctrl+S)', command=self.save_current).pack(side='right')
        tk.Button(navigation, text='Lưu và tiếp (PgDn)', command=self.save_and_next).pack(side='right', padx=8)

        quick = tk.Frame(root, padx=10)
        quick.pack(fill='x', pady=(0, 8))
        tk.Label(quick, text='Một chạm:').pack(side='left')
        tk.Button(quick, text='F5: Không nhiệm vụ', command=lambda: self.quick_save('negative')).pack(side='left', padx=5)
        tk.Button(quick, text='F6: Nhiệm vụ, không cấp xã', command=lambda: self.quick_save('task_not_commune')).pack(side='left', padx=5)
        tk.Button(quick, text='F7: Nhiệm vụ cấp xã', command=lambda: self.quick_save('task_commune')).pack(side='left', padx=5)

        footer = tk.Label(
            root,
            text=f'Bản sao đầu phiên: {backup_path} | Không hiển thị gợi ý máy | Chỉ lưu label_status=draft',
            anchor='w',
            padx=10,
            pady=5,
            fg='#555555',
        )
        footer.pack(fill='x')

        root.bind('<F1>', lambda _event: self.set_task('0'))
        root.bind('<F2>', lambda _event: self.set_task('1'))
        root.bind('<F3>', lambda _event: self.set_commune('0'))
        root.bind('<F4>', lambda _event: self.set_commune('1'))
        root.bind('<F5>', lambda _event: self.quick_save('negative'))
        root.bind('<F6>', lambda _event: self.quick_save('task_not_commune'))
        root.bind('<F7>', lambda _event: self.quick_save('task_commune'))
        root.bind('<Prior>', lambda _event: self.previous())
        root.bind('<Next>', lambda _event: self.save_and_next())
        root.bind('<Control-s>', lambda _event: self.save_current())
        self.show_current()

    def make_text_panel(self, parent, title, height, background):
        from tkinter.scrolledtext import ScrolledText
        frame = self.tk.LabelFrame(parent, text=title, padx=8, pady=5)
        frame.pack(fill='both', expand=(height >= 10), pady=4)
        widget = ScrolledText(frame, height=height, wrap='word', font=('Segoe UI', 11), background=background)
        widget.pack(fill='both', expand=True)
        widget.configure(state='disabled')
        return widget

    def set_panel(self, widget, text):
        widget.configure(state='normal')
        widget.delete('1.0', 'end')
        widget.insert('1.0', text or '')
        widget.configure(state='disabled')

    def first_incomplete_index(self):
        for index, row in enumerate(self.rows):
            if not is_complete(row):
                return index
        return 0

    def show_current(self):
        row = self.rows[self.index]
        context = self.context_map.get(row['segment_id'], {})
        previous = context.get('previous')
        following = context.get('next')
        self.set_panel(self.previous_text, previous['segment_text'] if previous else '[Đầu văn bản]')
        self.set_panel(self.current_text, row['segment_text'])
        self.set_panel(self.next_text, following['segment_text'] if following else '[Cuối văn bản]')
        self.task_var.set(row['task_present'])
        self.commune_var.set(row['commune_relevance'])
        self.notes_text.delete('1.0', 'end')
        self.notes_text.insert('1.0', row['notes'])
        self.notes_text.edit_modified(False)
        completed, total = progress(self.rows)
        self.status_var.set(f'Hàng {self.index + 1}/{total} | Đã hoàn thành {completed}/{total}')
        self.location_var.set(f'{row["document_id"]} | {row["source_location"]}')
        self.dirty = False

    def mark_dirty(self):
        self.dirty = True

    def on_notes_modified(self, _event=None):
        if self.notes_text.edit_modified():
            self.dirty = True
            self.notes_text.edit_modified(False)

    def on_task_change(self):
        if self.task_var.get() == '0':
            self.commune_var.set('0')
        self.dirty = True

    def set_task(self, value):
        self.task_var.set(value)
        self.on_task_change()

    def set_commune(self, value):
        if value == '1' and self.task_var.get() == '0':
            self.messagebox.showwarning('Nhãn không hợp lệ', 'Không thể đặt commune_relevance=1 khi task_present=0.')
            return
        self.commune_var.set(value)
        self.dirty = True

    def save_current(self):
        try:
            row = self.rows[self.index]
            before = {
                'task_present': row.get('task_present', ''),
                'commune_relevance': row.get('commune_relevance', ''),
                'label_status': row.get('label_status', ''),
            }
            apply_labels(
                row,
                self.task_var.get(),
                self.commune_var.get(),
                self.annotator_id,
                self.notes_text.get('1.0', 'end-1c'),
            )
            write_csv_atomic(self.input_path, self.headers, self.rows)
            append_audit_event(
                self.audit_path,
                {
                    'utc': datetime.now(timezone.utc).isoformat(),
                    'event_type': 'annotation.saved',
                    'session_id': self.session_id,
                    'input_file': self.input_path.name,
                    'segment_id': row['segment_id'],
                    'document_id': row['document_id'],
                    'annotator_id': self.annotator_id,
                    'row_index': self.index,
                    'before': before,
                    'after': {
                        'task_present': row['task_present'],
                        'commune_relevance': row['commune_relevance'],
                        'label_status': row['label_status'],
                    },
                    'notes_present': bool(row.get('notes', '').strip()),
                    'file_sha256_after': sha256(self.input_path),
                },
            )
            self.dirty = False
            completed, total = progress(self.rows)
            self.status_var.set(f'Hàng {self.index + 1}/{total} | Đã hoàn thành {completed}/{total} | Đã lưu')
            return True
        except Exception as exc:
            self.messagebox.showerror('Không thể lưu', str(exc))
            return False

    def quick_save(self, choice):
        task_present, commune_relevance = QUICK_LABELS[choice]
        self.task_var.set(task_present)
        self.commune_var.set(commune_relevance)
        self.dirty = True
        self.save_and_next()

    def save_and_next(self):
        if not self.save_current():
            return
        if self.index + 1 < len(self.rows):
            self.index += 1
            self.show_current()

    def previous(self):
        if self.dirty and not self.save_current():
            return
        if self.index > 0:
            self.index -= 1
            self.show_current()

    def next_incomplete(self):
        if self.dirty and not self.save_current():
            return
        for offset in range(1, len(self.rows) + 1):
            index = (self.index + offset) % len(self.rows)
            if not is_complete(self.rows[index]):
                self.index = index
                self.show_current()
                return
        self.messagebox.showinfo('Hoàn thành', 'Tất cả các hàng đã có nhãn draft hợp lệ.')

    def on_close(self):
        if self.dirty and not self.save_current():
            return
        try:
            append_audit_event(
                self.audit_path,
                {
                    'utc': datetime.now(timezone.utc).isoformat(),
                    'event_type': 'annotation.session_closed',
                    'session_id': self.session_id,
                    'input_file': self.input_path.name,
                    'annotator_id': self.annotator_id,
                    'file_sha256': sha256(self.input_path),
                },
            )
        except Exception as exc:
            self.messagebox.showwarning('Cảnh báo audit', f'Đã lưu nhãn nhưng không ghi được audit đóng phiên: {exc}')
        finally:
            release_lock(self.lock_path)
            self.root.destroy()


def launch_app(input_path, context_path, annotator_id, force_unlock=False):
    import tkinter as tk

    headers, rows = read_csv_rows(input_path)
    validate_annotation_file(input_path, headers, rows)
    if not rows:
        raise ValueError('File gán nhãn không có hàng dữ liệu.')
    context_headers, context_rows = read_csv_rows(context_path)
    validate_context(context_headers, context_rows)
    context_map = build_context_map(context_rows)
    missing_context = [row['segment_id'] for row in rows if row['segment_id'] not in context_map]
    if missing_context:
        raise ValueError(f'Có {len(missing_context)} segment_id không tìm thấy trong file ngữ cảnh.')

    lock_path = acquire_lock(input_path, force_unlock=force_unlock)
    backup_root = ROOT / 'evidence' / 'annotation_backups'
    try:
        backup_path = create_session_backup(input_path, backup_root)
        session_id = f'{os.getpid()}_{datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")}'
        audit_path = ROOT / 'evidence' / 'annotation_audit' / f'{input_path.stem}_{annotator_id}.jsonl'
        append_audit_event(
            audit_path,
            {
                'utc': datetime.now(timezone.utc).isoformat(),
                'event_type': 'annotation.session_started',
                'session_id': session_id,
                'input_file': input_path.name,
                'annotator_id': annotator_id,
                'input_sha256': sha256(input_path),
                'backup_file': backup_path.name,
            },
        )
        root = tk.Tk()
        AnnotationApp(
            root,
            input_path,
            headers,
            rows,
            context_map,
            annotator_id,
            backup_path,
            lock_path,
            audit_path,
            session_id,
        )
        root.mainloop()
    finally:
        release_lock(lock_path)


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description='Giao diện gán nhãn đoạn SF2026 chạy cục bộ trên Windows.')
    parser.add_argument('--input', required=True, help='File segments_annotatorA.csv hoặc segments_annotatorB.csv')
    parser.add_argument('--annotator-id', required=True, help='Mã người gán, ví dụ A01 hoặc B01')
    parser.add_argument('--context', default='data/processed/candidate_segments.csv')
    parser.add_argument('--check', action='store_true', help='Chỉ kiểm tra file và tiến độ, không mở giao diện')
    parser.add_argument('--force-unlock', action='store_true', help='Chỉ dùng khi chắc chắn không còn phiên gán nào đang mở')
    args = parser.parse_args()

    input_path = (ROOT / args.input).resolve() if not Path(args.input).is_absolute() else Path(args.input).resolve()
    context_path = (ROOT / args.context).resolve() if not Path(args.context).is_absolute() else Path(args.context).resolve()
    try:
        if args.check:
            raise SystemExit(check_only(input_path, context_path))
        launch_app(input_path, context_path, args.annotator_id, force_unlock=args.force_unlock)
    except ValueError as exc:
        raise SystemExit(f'LỖI: {exc}') from exc


if __name__ == '__main__':
    main()
