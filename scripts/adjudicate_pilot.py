#!/usr/bin/env python3
"""Giao diện adjudication pilot cục bộ, có toàn văn và truy vết.

Nguồn A/B, context và conflict chỉ được đọc. Kết quả được ghi vào một file
draft riêng, không cập nhật ``segments_gold.csv``. Toàn văn chỉ hiển thị trong
giao diện; file adjudication và audit không chép ``segment_text``.
"""

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STRUCTURAL_NOTE_PATTERN = re.compile(
    r'\[(?:SEG_|MERGE_|OCR_|TABLE_|READING_ORDER_|MISSING_TEXT|LAYOUT_LOSS)',
    re.IGNORECASE,
)
UNIT_STATUSES = {
    'valid',
    'needs_merge',
    'needs_source_check',
    'ocr_error',
    'exclude_invalid_unit',
}
OUTPUT_COLUMNS = [
    'document_id',
    'segment_id',
    'source_location',
    'label_a_task',
    'label_a_commune',
    'notes_a',
    'label_b_task',
    'label_b_commune',
    'notes_b',
    'conflict_fields',
    'review_reason',
    'unit_status',
    'resolved_task_present',
    'resolved_commune_relevance',
    'member_segment_ids',
    'adjudicator_id',
    'adjudicated_at_utc',
    'adjudication_rationale',
    'review_status',
    'research_status',
]


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


def require_columns(headers, required, name):
    missing = [column for column in required if column not in headers]
    if missing:
        raise ValueError(f'{name}: thiếu cột {", ".join(missing)}')


def validate_unique(rows, column, name):
    values = [str(row.get(column, '')).strip() for row in rows]
    if any(not value for value in values):
        raise ValueError(f'{name}: có {column} trống.')
    duplicates = [value for value, count in Counter(values).items() if count > 1]
    if duplicates:
        raise ValueError(f'{name}: có {len(duplicates)} {column} bị trùng.')


def write_csv_atomic(path, headers, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
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


def write_json_atomic(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f'.{path.name}.{os.getpid()}.tmp')
    try:
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def append_audit_event(path, payload):
    forbidden = {
        'segment_text',
        'source_text',
        'task_text',
        'notes_a',
        'notes_b',
        'adjudication_rationale',
    }
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
            f'Phiên adjudication khác đang mở hoặc còn lock cũ: {lock_path}. '
            'Chỉ dùng --force-unlock khi chắc chắn không còn cửa sổ đang chạy.'
        ) from exc
    os.write(descriptor, f'pid={os.getpid()}\nutc={datetime.now(timezone.utc).isoformat()}\n'.encode('utf-8'))
    os.close(descriptor)
    return lock_path


def release_lock(lock_path):
    if lock_path and lock_path.exists():
        lock_path.unlink()


def resolve_path(value):
    path = Path(value)
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def build_document_map(context_rows):
    result = {}
    for row in context_rows:
        result.setdefault(row['document_id'], []).append(row)
    return result


def conflict_map(conflict_rows):
    result = {}
    for row in conflict_rows:
        result.setdefault(row['segment_id'], set()).add(row['field'])
    return result


def build_queue(annotator_a, annotator_b, conflicts, mode='mandatory'):
    """Tạo queue mà không chép toàn văn; thứ tự giữ theo biểu A."""
    validate_unique(annotator_a, 'segment_id', 'annotator A')
    validate_unique(annotator_b, 'segment_id', 'annotator B')
    by_b = {row['segment_id']: row for row in annotator_b}
    if set(by_b) != {row['segment_id'] for row in annotator_a}:
        raise ValueError('Hai biểu A/B phải có đúng cùng tập segment_id.')
    conflicts_by_id = conflict_map(conflicts)
    rows = []
    for row_a in annotator_a:
        segment_id = row_a['segment_id']
        row_b = by_b[segment_id]
        has_conflict = segment_id in conflicts_by_id
        notes = f'{row_a.get("notes", "")}\n{row_b.get("notes", "")}'
        has_note = bool(notes.strip())
        has_structural = bool(STRUCTURAL_NOTE_PATTERN.search(notes))
        include = {
            'conflicts': has_conflict,
            'mandatory': has_conflict or has_structural,
            'all_noted': has_conflict or has_note,
        }[mode]
        if not include:
            continue
        reasons = []
        if has_conflict:
            reasons.append('conflict')
        if has_structural:
            reasons.append('structural_note')
        elif has_note:
            reasons.append('semantic_note')
        rows.append(
            {
                'document_id': row_a['document_id'],
                'segment_id': segment_id,
                'source_location': row_a['source_location'],
                'label_a_task': row_a['task_present'],
                'label_a_commune': row_a['commune_relevance'],
                'notes_a': row_a.get('notes', ''),
                'label_b_task': row_b['task_present'],
                'label_b_commune': row_b['commune_relevance'],
                'notes_b': row_b.get('notes', ''),
                'conflict_fields': ';'.join(sorted(conflicts_by_id.get(segment_id, set()))),
                'review_reason': ';'.join(reasons),
                'unit_status': '',
                'resolved_task_present': '',
                'resolved_commune_relevance': '',
                'member_segment_ids': segment_id,
                'adjudicator_id': '',
                'adjudicated_at_utc': '',
                'adjudication_rationale': '',
                'review_status': '',
                'research_status': 'PILOT_ADJUDICATION_NOT_GOLD',
            }
        )
    return rows


def validate_member_ids(value, current_segment_id, document_id, context_by_id):
    entered = [item.strip() for item in value.split(';') if item.strip()]
    if not entered:
        raise ValueError('member_segment_ids không được trống.')
    document_ids = [
        segment_id
        for segment_id, row in context_by_id.items()
        if row['document_id'] == document_id
    ]
    members = []
    for item in entered:
        if item in context_by_id:
            resolved = item
        else:
            matches = [segment_id for segment_id in document_ids if segment_id.endswith(f'_{item}')]
            if len(matches) != 1:
                raise ValueError(
                    f'Mã rút gọn {item!r} phải khớp đúng một segment trong tài liệu; hiện có {len(matches)}.'
                )
            resolved = matches[0]
        members.append(resolved)
    if len(members) != len(set(members)):
        raise ValueError('member_segment_ids có mã trùng.')
    if current_segment_id not in members:
        raise ValueError('member_segment_ids phải chứa segment hiện tại.')
    unknown = [item for item in members if item not in context_by_id]
    if unknown:
        raise ValueError(f'Không tìm thấy segment: {", ".join(unknown)}')
    cross_document = [item for item in members if context_by_id[item]['document_id'] != document_id]
    if cross_document:
        raise ValueError('Không được ghép segment thuộc tài liệu khác.')
    return members


def apply_adjudication(
    row,
    unit_status,
    task_present,
    commune_relevance,
    member_segment_ids,
    adjudicator_id,
    rationale,
    context_by_id,
):
    unit_status = unit_status.strip()
    adjudicator_id = adjudicator_id.strip()
    rationale = rationale.strip()
    if unit_status not in UNIT_STATUSES:
        raise ValueError(f'unit_status không hợp lệ: {unit_status}')
    if not adjudicator_id:
        raise ValueError('Phải có adjudicator_id.')
    if not rationale:
        raise ValueError('Phải ghi lý do adjudication trước khi lưu.')
    members = validate_member_ids(
        member_segment_ids,
        row['segment_id'],
        row['document_id'],
        context_by_id,
    )
    if unit_status == 'valid':
        if task_present not in ('0', '1'):
            raise ValueError('Đơn vị valid phải có task_present=0/1.')
        if task_present == '0':
            commune_relevance = '0'
        if commune_relevance not in ('0', '1'):
            raise ValueError('Đơn vị valid phải có commune_relevance=0/1.')
        if len(members) != 1:
            raise ValueError('Đơn vị valid chưa ghép chỉ được có segment hiện tại.')
        review_status = 'draft_adjudicated'
    elif unit_status == 'needs_merge':
        if len(members) < 2:
            raise ValueError('needs_merge phải liệt kê ít nhất hai member_segment_ids.')
        task_present = ''
        commune_relevance = ''
        review_status = 'pending_rework'
    else:
        if len(members) != 1:
            raise ValueError(f'{unit_status} chưa được phép ghép nhiều segment.')
        task_present = ''
        commune_relevance = ''
        review_status = 'pending_rework'

    row['unit_status'] = unit_status
    row['resolved_task_present'] = task_present
    row['resolved_commune_relevance'] = commune_relevance
    row['member_segment_ids'] = ';'.join(members)
    row['adjudicator_id'] = adjudicator_id
    row['adjudicated_at_utc'] = datetime.now(timezone.utc).isoformat()
    row['adjudication_rationale'] = rationale
    row['review_status'] = review_status
    row['research_status'] = 'PILOT_ADJUDICATION_NOT_GOLD'
    return row


def is_complete(row):
    return row.get('review_status') in {'draft_adjudicated', 'pending_rework'} and bool(
        row.get('adjudicator_id', '').strip()
    ) and bool(row.get('adjudication_rationale', '').strip())


def validate_output_rows(rows, context_by_id):
    validate_unique(rows, 'segment_id', 'adjudication')
    issues = []
    for index, row in enumerate(rows, 2):
        if not row.get('unit_status', '').strip():
            continue
        try:
            copy = dict(row)
            apply_adjudication(
                copy,
                row['unit_status'],
                row.get('resolved_task_present', ''),
                row.get('resolved_commune_relevance', ''),
                row.get('member_segment_ids', ''),
                row.get('adjudicator_id', ''),
                row.get('adjudication_rationale', ''),
                context_by_id,
            )
        except ValueError as exc:
            issues.append(f'Dòng {index}: {exc}')
    return issues


def source_manifest(paths, mode, row_count):
    return {
        'schema_version': 1,
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'queue_mode': mode,
        'row_count': row_count,
        'research_status': 'PILOT_ADJUDICATION_NOT_GOLD',
        'sources': {
            key: {'path': str(path.relative_to(ROOT)), 'sha256': sha256(path)}
            for key, path in paths.items()
        },
    }


def verify_manifest(manifest_path, paths, mode):
    if not manifest_path.is_file():
        raise ValueError(f'Thiếu manifest khóa nguồn: {manifest_path}')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('queue_mode') != mode:
        raise ValueError(
            f'Output được tạo với mode={manifest.get("queue_mode")}; '
            f'không thể mở bằng mode={mode}. Hãy dùng output khác.'
        )
    for key, path in paths.items():
        recorded = manifest.get('sources', {}).get(key, {}).get('sha256')
        current = sha256(path)
        if recorded != current:
            raise ValueError(f'Nguồn {key} đã thay đổi sau khi tạo adjudication; dừng để kiểm tra.')
    return manifest


def load_sources(args):
    paths = {
        'annotator_a': resolve_path(args.annotator_a),
        'annotator_b': resolve_path(args.annotator_b),
        'context': resolve_path(args.context),
        'conflicts': resolve_path(args.conflicts),
    }
    a_headers, a_rows = read_csv_rows(paths['annotator_a'])
    b_headers, b_rows = read_csv_rows(paths['annotator_b'])
    context_headers, context_rows = read_csv_rows(paths['context'])
    conflict_headers, conflict_rows = read_csv_rows(paths['conflicts'])
    annotation_columns = [
        'document_id', 'segment_id', 'source_location', 'task_present',
        'commune_relevance', 'annotator_id', 'label_status', 'notes',
    ]
    require_columns(a_headers, annotation_columns, paths['annotator_a'].name)
    require_columns(b_headers, annotation_columns, paths['annotator_b'].name)
    require_columns(context_headers, ['document_id', 'segment_id', 'source_location', 'segment_text'], paths['context'].name)
    require_columns(conflict_headers, ['segment_id', 'field', 'label_a', 'label_b'], paths['conflicts'].name)
    validate_unique(context_rows, 'segment_id', paths['context'].name)
    context_by_id = {row['segment_id']: row for row in context_rows}
    missing = [row['segment_id'] for row in a_rows if row['segment_id'] not in context_by_id]
    if missing:
        raise ValueError(f'Có {len(missing)} segment A/B không nằm trong context.')
    return paths, a_rows, b_rows, context_rows, conflict_rows, context_by_id


def prepare_or_load(args):
    paths, a_rows, b_rows, context_rows, conflict_rows, context_by_id = load_sources(args)
    output_path = resolve_path(args.output)
    manifest_path = output_path.with_suffix('.manifest.json')
    audit_path = output_path.with_suffix('.audit.jsonl')
    if output_path.exists():
        verify_manifest(manifest_path, paths, args.mode)
        headers, rows = read_csv_rows(output_path)
        require_columns(headers, OUTPUT_COLUMNS, output_path.name)
        return output_path, manifest_path, audit_path, headers, rows, context_rows, context_by_id

    rows = build_queue(a_rows, b_rows, conflict_rows, args.mode)
    write_csv_atomic(output_path, OUTPUT_COLUMNS, rows)
    manifest = source_manifest(paths, args.mode, len(rows))
    write_json_atomic(manifest_path, manifest)
    append_audit_event(
        audit_path,
        {
            'utc': datetime.now(timezone.utc).isoformat(),
            'event_type': 'adjudication.prepared',
            'output_file': output_path.name,
            'queue_mode': args.mode,
            'row_count': len(rows),
            'output_sha256': sha256(output_path),
            'source_hashes': {key: value['sha256'] for key, value in manifest['sources'].items()},
        },
    )
    return output_path, manifest_path, audit_path, OUTPUT_COLUMNS, rows, context_rows, context_by_id


class AdjudicationApp:
    def __init__(
        self,
        root,
        output_path,
        headers,
        rows,
        context_rows,
        context_by_id,
        adjudicator_id,
        backup_path,
        audit_path,
        lock_path,
        session_id,
    ):
        import tkinter as tk
        from tkinter import messagebox, ttk
        from tkinter.scrolledtext import ScrolledText

        self.tk = tk
        self.messagebox = messagebox
        self.ttk = ttk
        self.root = root
        self.output_path = output_path
        self.headers = headers
        self.rows = rows
        self.context_rows = context_rows
        self.context_by_id = context_by_id
        self.documents = build_document_map(context_rows)
        self.adjudicator_id = adjudicator_id
        self.backup_path = backup_path
        self.audit_path = audit_path
        self.lock_path = lock_path
        self.session_id = session_id
        self.index = self.first_incomplete_index()
        self.dirty = False

        root.title(f'Adjudication pilot SF2026 - {adjudicator_id}')
        root.geometry('1380x920')
        root.minsize(1050, 720)
        root.protocol('WM_DELETE_WINDOW', self.on_close)

        self.status_var = tk.StringVar()
        self.location_var = tk.StringVar()
        self.unit_status_var = tk.StringVar()
        self.task_var = tk.StringVar()
        self.commune_var = tk.StringVar()
        self.members_var = tk.StringVar()

        header = tk.Frame(root, padx=10, pady=7)
        header.pack(fill='x')
        tk.Label(header, textvariable=self.status_var, font=('Segoe UI', 11, 'bold')).pack(side='left')
        tk.Label(header, textvariable=self.location_var).pack(side='right')

        comparison = tk.Frame(root, padx=10)
        comparison.pack(fill='x')
        self.a_text = self.make_readonly_panel(comparison, 'Người A', 4, '#eef6ff', side='left')
        self.b_text = self.make_readonly_panel(comparison, 'Người B', 4, '#f4efff', side='left')

        notebook = ttk.Notebook(root)
        notebook.pack(fill='both', expand=True, padx=10, pady=6)
        near_tab = tk.Frame(notebook)
        full_tab = tk.Frame(notebook)
        notebook.add(near_tab, text='Ngữ cảnh ±3 segment')
        notebook.add(full_tab, text='Toàn văn cùng tài liệu')
        self.near_text = ScrolledText(near_tab, wrap='word', font=('Segoe UI', 11), background='#fffbe6')
        self.near_text.pack(fill='both', expand=True)
        self.near_text.configure(state='disabled')
        self.full_text = ScrolledText(full_tab, wrap='word', font=('Segoe UI', 10), background='#ffffff')
        self.full_text.pack(fill='both', expand=True)
        self.full_text.tag_configure('current', background='#fff2a8', font=('Segoe UI', 10, 'bold'))
        self.full_text.configure(state='disabled')

        controls = tk.Frame(root, padx=10, pady=5)
        controls.pack(fill='x')
        status_box = tk.LabelFrame(controls, text='Trạng thái đơn vị', padx=6, pady=4)
        status_box.pack(side='left', fill='x', expand=True)
        for text, value in [
            ('Valid', 'valid'),
            ('Cần ghép', 'needs_merge'),
            ('Kiểm tra nguồn', 'needs_source_check'),
            ('Lỗi OCR', 'ocr_error'),
            ('Loại đơn vị lỗi', 'exclude_invalid_unit'),
        ]:
            tk.Radiobutton(
                status_box,
                text=text,
                variable=self.unit_status_var,
                value=value,
                command=self.mark_dirty,
            ).pack(side='left', padx=3)

        labels = tk.Frame(root, padx=10, pady=4)
        labels.pack(fill='x')
        task_box = tk.LabelFrame(labels, text='Nhãn task', padx=6, pady=4)
        task_box.pack(side='left', padx=(0, 8))
        for text, value in [('Trống', ''), ('0', '0'), ('1', '1')]:
            tk.Radiobutton(task_box, text=text, variable=self.task_var, value=value, command=self.on_task_change).pack(side='left')
        commune_box = tk.LabelFrame(labels, text='Nhãn cấp xã', padx=6, pady=4)
        commune_box.pack(side='left')
        for text, value in [('Trống', ''), ('0', '0'), ('1', '1')]:
            tk.Radiobutton(commune_box, text=text, variable=self.commune_var, value=value, command=self.mark_dirty).pack(side='left')
        tk.Label(labels, text='Member segment IDs (;):').pack(side='left', padx=(15, 5))
        tk.Entry(labels, textvariable=self.members_var, width=55).pack(side='left', fill='x', expand=True)
        self.members_var.trace_add('write', lambda *_args: self.mark_dirty())

        rationale_frame = tk.LabelFrame(root, text='Lý do adjudication', padx=10, pady=5)
        rationale_frame.pack(fill='x', padx=10, pady=4)
        self.rationale_text = ScrolledText(rationale_frame, height=3, wrap='word', font=('Segoe UI', 10))
        self.rationale_text.pack(fill='x')
        self.rationale_text.bind('<<Modified>>', self.on_rationale_modified)

        navigation = tk.Frame(root, padx=10, pady=7)
        navigation.pack(fill='x')
        tk.Button(navigation, text='← Trước', command=self.previous).pack(side='left')
        tk.Button(navigation, text='Hàng chưa xử lý tiếp', command=self.next_incomplete).pack(side='left', padx=7)
        tk.Button(navigation, text='F5: valid 0/0', command=lambda: self.quick_valid('0', '0')).pack(side='left', padx=3)
        tk.Button(navigation, text='F6: valid 1/0', command=lambda: self.quick_valid('1', '0')).pack(side='left', padx=3)
        tk.Button(navigation, text='F7: valid 1/1', command=lambda: self.quick_valid('1', '1')).pack(side='left', padx=3)
        tk.Button(navigation, text='F8: cần ghép', command=self.quick_needs_merge).pack(side='left', padx=3)
        tk.Button(navigation, text='Lưu và tiếp', command=self.save_and_next).pack(side='right')
        tk.Button(navigation, text='Lưu', command=self.save_current).pack(side='right', padx=7)

        root.bind('<F5>', lambda _event: self.quick_valid('0', '0'))
        root.bind('<F6>', lambda _event: self.quick_valid('1', '0'))
        root.bind('<F7>', lambda _event: self.quick_valid('1', '1'))
        root.bind('<F8>', lambda _event: self.quick_needs_merge())
        root.bind('<Prior>', lambda _event: self.previous())
        root.bind('<Next>', lambda _event: self.save_and_next())
        root.bind('<Control-s>', lambda _event: self.save_current())
        self.show_current()

    def make_readonly_panel(self, parent, title, height, background, side):
        from tkinter.scrolledtext import ScrolledText

        frame = self.tk.LabelFrame(parent, text=title, padx=5, pady=4)
        frame.pack(side=side, fill='both', expand=True, padx=3)
        widget = ScrolledText(frame, height=height, wrap='word', font=('Segoe UI', 10), background=background)
        widget.pack(fill='both', expand=True)
        widget.configure(state='disabled')
        return widget

    @staticmethod
    def first_incomplete(rows):
        for index, row in enumerate(rows):
            if not is_complete(row):
                return index
        return 0

    def first_incomplete_index(self):
        return self.first_incomplete(self.rows)

    def set_readonly(self, widget, value):
        widget.configure(state='normal')
        widget.delete('1.0', 'end')
        widget.insert('1.0', value or '')
        widget.configure(state='disabled')

    def show_current(self):
        row = self.rows[self.index]
        completed = sum(is_complete(item) for item in self.rows)
        self.status_var.set(
            f'Hàng {self.index + 1}/{len(self.rows)} | Hoàn thành {completed}/{len(self.rows)} | '
            f'Lý do: {row["review_reason"]}'
        )
        self.location_var.set(f'{row["document_id"]} | {row["source_location"]} | {row["segment_id"]}')
        self.set_readonly(
            self.a_text,
            f'task={row["label_a_task"]}; commune={row["label_a_commune"]}\n{row["notes_a"]}',
        )
        self.set_readonly(
            self.b_text,
            f'task={row["label_b_task"]}; commune={row["label_b_commune"]}\n{row["notes_b"]}',
        )
        self.render_near_context(row)
        self.render_full_document(row)
        self.unit_status_var.set(row['unit_status'])
        self.task_var.set(row['resolved_task_present'])
        self.commune_var.set(row['resolved_commune_relevance'])
        self.members_var.set(row['member_segment_ids'])
        self.rationale_text.delete('1.0', 'end')
        self.rationale_text.insert('1.0', row['adjudication_rationale'])
        self.rationale_text.edit_modified(False)
        self.dirty = False

    def render_near_context(self, row):
        document_rows = self.documents[row['document_id']]
        current_index = next(index for index, item in enumerate(document_rows) if item['segment_id'] == row['segment_id'])
        start = max(0, current_index - 3)
        end = min(len(document_rows), current_index + 4)
        parts = []
        for index in range(start, end):
            item = document_rows[index]
            marker = '>>> ĐANG XỬ LÝ' if index == current_index else '   '
            parts.append(f'{marker} [{item["source_location"]} | {item["segment_id"]}]\n{item["segment_text"]}')
        self.set_readonly(self.near_text, '\n\n'.join(parts))

    def render_full_document(self, row):
        self.full_text.configure(state='normal')
        self.full_text.delete('1.0', 'end')
        current_mark = None
        for item in self.documents[row['document_id']]:
            start = self.full_text.index('end-1c')
            marker = '>>> ĐANG XỬ LÝ' if item['segment_id'] == row['segment_id'] else '   '
            value = f'{marker} [{item["source_location"]} | {item["segment_id"]}]\n{item["segment_text"]}\n\n'
            self.full_text.insert('end', value)
            if item['segment_id'] == row['segment_id']:
                end = self.full_text.index('end-1c')
                self.full_text.tag_add('current', start, end)
                current_mark = start
        self.full_text.configure(state='disabled')
        if current_mark:
            self.full_text.see(current_mark)

    def mark_dirty(self):
        self.dirty = True

    def on_rationale_modified(self, _event=None):
        if self.rationale_text.edit_modified():
            self.dirty = True
            self.rationale_text.edit_modified(False)

    def on_task_change(self):
        if self.task_var.get() == '0':
            self.commune_var.set('0')
        self.dirty = True

    def quick_valid(self, task_present, commune_relevance):
        self.unit_status_var.set('valid')
        self.task_var.set(task_present)
        self.commune_var.set(commune_relevance)
        self.members_var.set(self.rows[self.index]['segment_id'])
        self.dirty = True
        self.save_and_next()

    def quick_needs_merge(self):
        self.unit_status_var.set('needs_merge')
        self.task_var.set('')
        self.commune_var.set('')
        self.dirty = True
        entered = [item.strip() for item in self.members_var.get().split(';') if item.strip()]
        if len(entered) < 2:
            self.messagebox.showinfo(
                'Cần nhập mapping',
                'Hãy điền ít nhất hai member_segment_ids, phân cách bằng dấu ;, rồi lưu.',
            )

    def save_current(self):
        row = self.rows[self.index]
        try:
            before = {
                'unit_status': row.get('unit_status', ''),
                'resolved_task_present': row.get('resolved_task_present', ''),
                'resolved_commune_relevance': row.get('resolved_commune_relevance', ''),
                'member_segment_ids': row.get('member_segment_ids', ''),
            }
            apply_adjudication(
                row,
                self.unit_status_var.get(),
                self.task_var.get(),
                self.commune_var.get(),
                self.members_var.get(),
                self.adjudicator_id,
                self.rationale_text.get('1.0', 'end-1c'),
                self.context_by_id,
            )
            write_csv_atomic(self.output_path, self.headers, self.rows)
            append_audit_event(
                self.audit_path,
                {
                    'utc': datetime.now(timezone.utc).isoformat(),
                    'event_type': 'adjudication.saved',
                    'session_id': self.session_id,
                    'output_file': self.output_path.name,
                    'segment_id': row['segment_id'],
                    'document_id': row['document_id'],
                    'adjudicator_id': self.adjudicator_id,
                    'before': before,
                    'after': {
                        'unit_status': row['unit_status'],
                        'resolved_task_present': row['resolved_task_present'],
                        'resolved_commune_relevance': row['resolved_commune_relevance'],
                        'member_segment_ids': row['member_segment_ids'],
                    },
                    'rationale_present': bool(row['adjudication_rationale']),
                    'output_sha256_after': sha256(self.output_path),
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
        self.messagebox.showinfo('Hoàn thành', 'Tất cả hàng trong queue đã được xử lý draft.')

    def on_close(self):
        if self.dirty and not self.save_current():
            return
        try:
            append_audit_event(
                self.audit_path,
                {
                    'utc': datetime.now(timezone.utc).isoformat(),
                    'event_type': 'adjudication.session_closed',
                    'session_id': self.session_id,
                    'output_file': self.output_path.name,
                    'adjudicator_id': self.adjudicator_id,
                    'output_sha256': sha256(self.output_path),
                },
            )
        except Exception as exc:
            self.messagebox.showwarning('Cảnh báo audit', f'Không ghi được audit đóng phiên: {exc}')
        finally:
            release_lock(self.lock_path)
            self.root.destroy()


def check_command(args):
    paths, a_rows, b_rows, context_rows, conflict_rows, context_by_id = load_sources(args)
    output_path = resolve_path(args.output)
    if not output_path.exists():
        queue = build_queue(a_rows, b_rows, conflict_rows, args.mode)
        print(f'Chưa tạo output. Queue mode={args.mode}: {len(queue)} segment.')
        return 0
    verify_manifest(output_path.with_suffix('.manifest.json'), paths, args.mode)
    headers, rows = read_csv_rows(output_path)
    require_columns(headers, OUTPUT_COLUMNS, output_path.name)
    issues = validate_output_rows(rows, context_by_id)
    completed = sum(is_complete(row) for row in rows)
    statuses = Counter(row['unit_status'] or 'unreviewed' for row in rows)
    print(f'File: {output_path}')
    print(f'Tiến độ: {completed}/{len(rows)}; trạng thái: {dict(sorted(statuses.items()))}')
    if issues:
        for issue in issues:
            print(f'LỖI: {issue}')
        return 1
    print('Hợp lệ về kỹ thuật; kết quả vẫn là pilot adjudication draft, chưa phải gold.')
    return 0


def launch(args):
    import tkinter as tk

    output_path, _manifest_path, audit_path, headers, rows, context_rows, context_by_id = prepare_or_load(args)
    if not rows:
        raise ValueError('Queue adjudication không có hàng.')
    # Các quyết định draft chưa hợp lệ (ví dụ thiếu lý do) vẫn phải mở được
    # để adjudicator sửa; lệnh --check sẽ liệt kê lỗi còn lại.

    lock_path = acquire_lock(output_path, args.force_unlock)
    backup_root = ROOT / 'evidence' / 'adjudication_backups'
    backup_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
    backup_path = backup_root / f'{output_path.stem}_{stamp}{output_path.suffix}'
    try:
        shutil.copy2(output_path, backup_path)
        if sha256(output_path) != sha256(backup_path):
            raise ValueError('Hash backup adjudication không khớp.')
        session_id = f'{os.getpid()}_{stamp}'
        append_audit_event(
            audit_path,
            {
                'utc': datetime.now(timezone.utc).isoformat(),
                'event_type': 'adjudication.session_started',
                'session_id': session_id,
                'output_file': output_path.name,
                'adjudicator_id': args.adjudicator_id,
                'output_sha256': sha256(output_path),
                'backup_file': backup_path.name,
            },
        )
        root = tk.Tk()
        AdjudicationApp(
            root,
            output_path,
            headers,
            rows,
            context_rows,
            context_by_id,
            args.adjudicator_id,
            backup_path,
            audit_path,
            lock_path,
            session_id,
        )
        root.mainloop()
    finally:
        release_lock(lock_path)


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description='Adjudication pilot A/B có toàn văn, mapping và audit.')
    parser.add_argument('--annotator-a', default='data/annotations/segments_annotatorA.csv')
    parser.add_argument('--annotator-b', default='data/annotations/segments_annotatorB.csv')
    parser.add_argument('--context', default='data/processed/candidate_segments.csv')
    parser.add_argument('--conflicts', default='results/errors/annotation_conflicts.csv')
    parser.add_argument('--output', default='data/annotations/pilot_adjudication.csv')
    parser.add_argument('--mode', choices=['conflicts', 'mandatory', 'all_noted'], default='mandatory')
    parser.add_argument('--adjudicator-id', default='ADJ01')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--force-unlock', action='store_true')
    args = parser.parse_args()

    try:
        if args.check:
            raise SystemExit(check_command(args))
        launch(args)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(f'LỖI: {exc}') from exc


if __name__ == '__main__':
    main()
