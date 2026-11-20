#!/usr/bin/env python3
"""Giao diện gán nhãn annotation-unit cho batch gold mở rộng.

Chỉ mở biểu annotator A/B; context lấy từ unit proposals nhưng không hiển thị
heuristic, suggestion hoặc nhãn pilot. Mọi lưu có backup, lock và audit không
chứa toàn văn.
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
    'document_id', 'annotation_unit_id', 'source_locations',
    'member_segment_ids', 'unit_text', 'task_present', 'commune_relevance',
    'annotator_id', 'label_status', 'notes',
]
CONTEXT_COLUMNS = [
    'document_id', 'annotation_unit_id', 'source_locations',
    'member_segment_ids', 'unit_text',
]
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
        return reader.fieldnames or [], list(reader)


def validate_form(path, headers, rows):
    name = path.name.lower()
    if 'annotator' not in name or not name.endswith('.csv'):
        raise ValueError('Chỉ được mở biểu annotation-unit dành cho annotator A/B.')
    missing = [column for column in REQUIRED_COLUMNS if column not in headers]
    if missing:
        raise ValueError(f'Biểu gán nhãn thiếu cột: {", ".join(missing)}')
    ids = [row['annotation_unit_id'] for row in rows]
    if any(not value.strip() for value in ids) or len(ids) != len(set(ids)):
        raise ValueError('annotation_unit_id phải đầy đủ và duy nhất.')
    for index, row in enumerate(rows, 2):
        for field in ('task_present', 'commune_relevance'):
            if row[field] not in ('', '0', '1'):
                raise ValueError(f'Dòng {index}: {field} phải trống, 0 hoặc 1.')
        if row['task_present'] == '0' and row['commune_relevance'] == '1':
            raise ValueError(f'Dòng {index}: task=0 không thể có commune=1.')


def validate_context(headers, rows):
    missing = [column for column in CONTEXT_COLUMNS if column not in headers]
    if missing:
        raise ValueError(f'Context units thiếu cột: {", ".join(missing)}')
    ids = [row['annotation_unit_id'] for row in rows]
    if any(not value.strip() for value in ids) or len(ids) != len(set(ids)):
        raise ValueError('Context có annotation_unit_id trống/trùng.')


def write_csv_atomic(path, headers, rows):
    temp = path.with_name(f'.{path.name}.{os.getpid()}.tmp')
    try:
        with temp.open('w', newline='', encoding='utf-8-sig') as stream:
            writer = csv.DictWriter(stream, fieldnames=headers, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def append_audit(path, payload):
    forbidden = {'unit_text', 'notes', 'source_text', 'task_text'}
    leaked = forbidden.intersection(payload)
    if leaked:
        raise ValueError(f'Audit không được chứa trường nhạy cảm: {", ".join(sorted(leaked))}')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, separators=(',', ':')) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


def acquire_lock(path, force_unlock=False):
    lock_path = path.with_name(f'.{path.name}.lock')
    if force_unlock and lock_path.exists():
        lock_path.unlink()
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise ValueError(
            f'Biểu đang mở hoặc còn lock cũ: {lock_path}. '
            'Chỉ dùng --force-unlock khi chắc chắn không còn cửa sổ.'
        ) from exc
    os.write(descriptor, f'pid={os.getpid()}\nutc={datetime.now(timezone.utc).isoformat()}\n'.encode('utf-8'))
    os.close(descriptor)
    return lock_path


def release_lock(lock_path):
    if lock_path and lock_path.exists():
        lock_path.unlink()


def apply_labels(row, task, commune, annotator_id, notes):
    if task not in ('', '0', '1'):
        raise ValueError('task_present phải trống, 0 hoặc 1.')
    if task == '0':
        commune = '0'
    if commune not in ('', '0', '1'):
        raise ValueError('commune_relevance phải trống, 0 hoặc 1.')
    if task == '0' and commune == '1':
        raise ValueError('task=0 không thể có commune=1.')
    complete = task in ('0', '1') and commune in ('0', '1') and bool(annotator_id.strip())
    row['task_present'] = task
    row['commune_relevance'] = commune
    row['annotator_id'] = annotator_id.strip() if complete else ''
    row['label_status'] = 'draft' if complete else ''
    row['notes'] = notes.strip()
    return row


def is_complete(row):
    return (
        row.get('task_present') in ('0', '1')
        and row.get('commune_relevance') in ('0', '1')
        and bool(row.get('annotator_id', '').strip())
        and row.get('label_status') == 'draft'
    )


def build_document_map(rows):
    result = {}
    for row in rows:
        result.setdefault(row['document_id'], []).append(row)
    return result


def check_only(input_path, context_path):
    headers, rows = read_csv_rows(input_path)
    validate_form(input_path, headers, rows)
    context_headers, context_rows = read_csv_rows(context_path)
    validate_context(context_headers, context_rows)
    context_ids = {row['annotation_unit_id'] for row in context_rows}
    missing = [row['annotation_unit_id'] for row in rows if row['annotation_unit_id'] not in context_ids]
    completed = sum(is_complete(row) for row in rows)
    print(f'File hợp lệ: {input_path}')
    print(f'Tiến độ: {completed}/{len(rows)}; thiếu context: {len(missing)}')
    return 0 if not missing else 1


class UnitAnnotationApp:
    def __init__(self, root, input_path, headers, rows, context_rows, annotator_id, backup_path, lock_path, audit_path, session_id):
        import tkinter as tk
        from tkinter import messagebox, ttk
        from tkinter.scrolledtext import ScrolledText

        self.tk = tk
        self.messagebox = messagebox
        self.root = root
        self.input_path = input_path
        self.headers = headers
        self.rows = rows
        self.context_by_id = {row['annotation_unit_id']: row for row in context_rows}
        self.documents = build_document_map(context_rows)
        self.annotator_id = annotator_id
        self.backup_path = backup_path
        self.lock_path = lock_path
        self.audit_path = audit_path
        self.session_id = session_id
        self.index = self.first_incomplete_index()
        self.dirty = False

        root.title(f'Gán annotation units SF2026 - {input_path.name} - {annotator_id}')
        root.geometry('1380x920')
        root.minsize(1040, 720)
        root.protocol('WM_DELETE_WINDOW', self.on_close)

        self.status_var = tk.StringVar()
        self.location_var = tk.StringVar()
        self.task_var = tk.StringVar()
        self.commune_var = tk.StringVar()

        header = tk.Frame(root, padx=10, pady=7)
        header.pack(fill='x')
        tk.Label(header, textvariable=self.status_var, font=('Segoe UI', 11, 'bold')).pack(side='left')
        tk.Label(header, textvariable=self.location_var).pack(side='right')

        current_frame = tk.LabelFrame(root, text='Annotation unit đang gán', padx=8, pady=5)
        current_frame.pack(fill='both', expand=True, padx=10, pady=4)
        self.current_text = ScrolledText(current_frame, height=9, wrap='word', font=('Segoe UI', 12), background='#fffbe6')
        self.current_text.pack(fill='both', expand=True)
        self.current_text.configure(state='disabled')

        notebook = ttk.Notebook(root)
        notebook.pack(fill='both', expand=True, padx=10, pady=4)
        near_tab = tk.Frame(notebook)
        full_tab = tk.Frame(notebook)
        notebook.add(near_tab, text='Ngữ cảnh ±3 unit')
        notebook.add(full_tab, text='Toàn văn cùng tài liệu')
        self.near_text = ScrolledText(near_tab, height=8, wrap='word', font=('Segoe UI', 10), background='#f4f4f4')
        self.near_text.pack(fill='both', expand=True)
        self.near_text.configure(state='disabled')
        self.full_text = ScrolledText(full_tab, height=8, wrap='word', font=('Segoe UI', 10))
        self.full_text.pack(fill='both', expand=True)
        self.full_text.tag_configure('current', background='#fff2a8', font=('Segoe UI', 10, 'bold'))
        self.full_text.configure(state='disabled')

        controls = tk.Frame(root, padx=10, pady=5)
        controls.pack(fill='x')
        task_box = tk.LabelFrame(controls, text='Có nhiệm vụ?', padx=6, pady=4)
        task_box.pack(side='left', padx=(0, 8))
        for text, value in [('Chưa chọn', ''), ('Không - F1', '0'), ('Có - F2', '1')]:
            tk.Radiobutton(task_box, text=text, variable=self.task_var, value=value, command=self.on_task_change).pack(side='left')
        commune_box = tk.LabelFrame(controls, text='Thuộc trách nhiệm cấp xã?', padx=6, pady=4)
        commune_box.pack(side='left')
        for text, value in [('Chưa chọn', ''), ('Không - F3', '0'), ('Có - F4', '1')]:
            tk.Radiobutton(commune_box, text=text, variable=self.commune_var, value=value, command=self.mark_dirty).pack(side='left')

        notes_frame = tk.LabelFrame(root, text='Ghi chú', padx=8, pady=5)
        notes_frame.pack(fill='x', padx=10, pady=4)
        self.notes_text = ScrolledText(notes_frame, height=3, wrap='word', font=('Segoe UI', 10))
        self.notes_text.pack(fill='x')
        self.notes_text.bind('<<Modified>>', self.on_notes_modified)

        navigation = tk.Frame(root, padx=10, pady=7)
        navigation.pack(fill='x')
        tk.Button(navigation, text='← Trước (PgUp)', command=self.previous).pack(side='left')
        tk.Button(navigation, text='Unit chưa gán tiếp', command=self.next_incomplete).pack(side='left', padx=6)
        tk.Button(navigation, text='F5: 0/0', command=lambda: self.quick_save('negative')).pack(side='left', padx=3)
        tk.Button(navigation, text='F6: 1/0', command=lambda: self.quick_save('task_not_commune')).pack(side='left', padx=3)
        tk.Button(navigation, text='F7: 1/1', command=lambda: self.quick_save('task_commune')).pack(side='left', padx=3)
        tk.Button(navigation, text='Lưu (Ctrl+S)', command=self.save_current).pack(side='right')
        tk.Button(navigation, text='Lưu và tiếp (PgDn)', command=self.save_and_next).pack(side='right', padx=6)

        footer = tk.Label(
            root,
            text='Không hiển thị master/heuristic/suggestion | Chỉ lưu draft | Có backup, lock và audit',
            anchor='w', padx=10, pady=4, fg='#555555',
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

    def first_incomplete_index(self):
        for index, row in enumerate(self.rows):
            if not is_complete(row):
                return index
        return 0

    def set_readonly(self, widget, value):
        widget.configure(state='normal')
        widget.delete('1.0', 'end')
        widget.insert('1.0', value or '')
        widget.configure(state='disabled')

    def show_current(self):
        row = self.rows[self.index]
        context = self.context_by_id[row['annotation_unit_id']]
        completed = sum(is_complete(item) for item in self.rows)
        self.status_var.set(f'Hàng {self.index + 1}/{len(self.rows)} | Hoàn thành {completed}/{len(self.rows)}')
        self.location_var.set(f'{row["document_id"]} | {row["source_locations"]} | {row["annotation_unit_id"]}')
        self.set_readonly(self.current_text, row['unit_text'])
        self.render_near(context)
        self.render_full(context)
        self.task_var.set(row['task_present'])
        self.commune_var.set(row['commune_relevance'])
        self.notes_text.delete('1.0', 'end')
        self.notes_text.insert('1.0', row['notes'])
        self.notes_text.edit_modified(False)
        self.dirty = False

    def render_near(self, current):
        document_rows = self.documents[current['document_id']]
        current_index = next(index for index, row in enumerate(document_rows) if row['annotation_unit_id'] == current['annotation_unit_id'])
        start = max(0, current_index - 3)
        end = min(len(document_rows), current_index + 4)
        parts = []
        for index in range(start, end):
            row = document_rows[index]
            marker = '>>> ĐANG GÁN' if index == current_index else '   '
            parts.append(f'{marker} [{row["source_locations"]} | {row["annotation_unit_id"]}]\n{row["unit_text"]}')
        self.set_readonly(self.near_text, '\n\n'.join(parts))

    def render_full(self, current):
        self.full_text.configure(state='normal')
        self.full_text.delete('1.0', 'end')
        current_mark = None
        for row in self.documents[current['document_id']]:
            start = self.full_text.index('end-1c')
            marker = '>>> ĐANG GÁN' if row['annotation_unit_id'] == current['annotation_unit_id'] else '   '
            value = f'{marker} [{row["source_locations"]} | {row["annotation_unit_id"]}]\n{row["unit_text"]}\n\n'
            self.full_text.insert('end', value)
            if row['annotation_unit_id'] == current['annotation_unit_id']:
                end = self.full_text.index('end-1c')
                self.full_text.tag_add('current', start, end)
                current_mark = start
        self.full_text.configure(state='disabled')
        if current_mark:
            self.full_text.see(current_mark)

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
            self.messagebox.showwarning('Nhãn không hợp lệ', 'Không thể đặt commune=1 khi task=0.')
            return
        self.commune_var.set(value)
        self.dirty = True

    def quick_save(self, choice):
        task, commune = QUICK_LABELS[choice]
        self.task_var.set(task)
        self.commune_var.set(commune)
        self.dirty = True
        self.save_and_next()

    def save_current(self):
        row = self.rows[self.index]
        try:
            before = {'task_present': row['task_present'], 'commune_relevance': row['commune_relevance'], 'label_status': row['label_status']}
            apply_labels(
                row,
                self.task_var.get(),
                self.commune_var.get(),
                self.annotator_id,
                self.notes_text.get('1.0', 'end-1c'),
            )
            write_csv_atomic(self.input_path, self.headers, self.rows)
            append_audit(
                self.audit_path,
                {
                    'utc': datetime.now(timezone.utc).isoformat(),
                    'event_type': 'unit_annotation.saved',
                    'session_id': self.session_id,
                    'input_file': self.input_path.name,
                    'annotation_unit_id': row['annotation_unit_id'],
                    'document_id': row['document_id'],
                    'annotator_id': self.annotator_id,
                    'before': before,
                    'after': {'task_present': row['task_present'], 'commune_relevance': row['commune_relevance'], 'label_status': row['label_status']},
                    'notes_present': bool(row['notes']),
                    'file_sha256_after': sha256(self.input_path),
                },
            )
            self.dirty = False
            return True
        except Exception as exc:
            self.messagebox.showerror('Không thể lưu', str(exc))
            return False

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
        self.messagebox.showinfo('Hoàn thành', 'Tất cả unit đã có nhãn draft hợp lệ.')

    def on_close(self):
        if self.dirty and not self.save_current():
            return
        try:
            append_audit(
                self.audit_path,
                {
                    'utc': datetime.now(timezone.utc).isoformat(),
                    'event_type': 'unit_annotation.session_closed',
                    'session_id': self.session_id,
                    'input_file': self.input_path.name,
                    'annotator_id': self.annotator_id,
                    'file_sha256': sha256(self.input_path),
                },
            )
        finally:
            release_lock(self.lock_path)
            self.root.destroy()


def launch(input_path, context_path, annotator_id, force_unlock=False):
    import tkinter as tk

    headers, rows = read_csv_rows(input_path)
    validate_form(input_path, headers, rows)
    if not rows:
        raise ValueError('Biểu gán nhãn không có hàng.')
    context_headers, context_rows = read_csv_rows(context_path)
    validate_context(context_headers, context_rows)
    context_ids = {row['annotation_unit_id'] for row in context_rows}
    missing = [row['annotation_unit_id'] for row in rows if row['annotation_unit_id'] not in context_ids]
    if missing:
        raise ValueError(f'Có {len(missing)} annotation_unit_id không có trong context.')

    lock_path = acquire_lock(input_path, force_unlock)
    backup_root = ROOT / 'evidence' / 'unit_annotation_backups'
    backup_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
    backup_path = backup_root / f'{input_path.stem}_{stamp}{input_path.suffix}'
    audit_path = ROOT / 'evidence' / 'unit_annotation_audit' / f'{input_path.stem}_{annotator_id}.jsonl'
    try:
        shutil.copy2(input_path, backup_path)
        if sha256(input_path) != sha256(backup_path):
            raise ValueError('Hash backup biểu annotation-unit không khớp.')
        session_id = f'{os.getpid()}_{stamp}'
        append_audit(
            audit_path,
            {
                'utc': datetime.now(timezone.utc).isoformat(),
                'event_type': 'unit_annotation.session_started',
                'session_id': session_id,
                'input_file': input_path.name,
                'annotator_id': annotator_id,
                'input_sha256': sha256(input_path),
                'backup_file': backup_path.name,
            },
        )
        root = tk.Tk()
        UnitAnnotationApp(root, input_path, headers, rows, context_rows, annotator_id, backup_path, lock_path, audit_path, session_id)
        root.mainloop()
    finally:
        release_lock(lock_path)


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description='Giao diện gán annotation-unit A/B cục bộ.')
    parser.add_argument('--input', required=True)
    parser.add_argument('--annotator-id', required=True)
    parser.add_argument('--context', default='data/annotations/annotation_unit_proposals.csv')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--force-unlock', action='store_true')
    args = parser.parse_args()
    input_path = Path(args.input).resolve() if Path(args.input).is_absolute() else (ROOT / args.input).resolve()
    context_path = Path(args.context).resolve() if Path(args.context).is_absolute() else (ROOT / args.context).resolve()
    try:
        if args.check:
            raise SystemExit(check_only(input_path, context_path))
        launch(input_path, context_path, args.annotator_id, args.force_unlock)
    except ValueError as exc:
        raise SystemExit(f'LỖI: {exc}') from exc


if __name__ == '__main__':
    main()
