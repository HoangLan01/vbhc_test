#!/usr/bin/env python3
"""Chuẩn bị và áp dụng review metadata manifest có backup/audit.

Gợi ý ngày/family chỉ hỗ trợ người duyệt. Chỉ hàng ``review_status=approved``
và đủ mọi trường bắt buộc mới được áp dụng vào manifest.
"""

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REVIEW_COLUMNS = [
    'document_id', 'filename', 'file_sha256', 'family_id', 'family_suggestions',
    'doc_date', 'date_suggestion', 'date_suggestion_source', 'doc_type',
    'source_url_or_archive', 'permission_basis', 'access_level', 'anonymized',
    'reviewer_id', 'review_status', 'review_notes', 'research_status',
]
EDITABLE_FIELDS = [
    'family_id', 'doc_date', 'doc_type', 'source_url_or_archive',
    'permission_basis', 'access_level', 'anonymized',
]
REQUIRED_FOR_APPROVAL = [
    'family_id', 'doc_date', 'source_url_or_archive', 'permission_basis',
    'access_level', 'anonymized', 'reviewer_id',
]


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def read_csv_rows(path, required=False):
    if not path.is_file():
        if required:
            raise ValueError(f'Không tìm thấy file: {path}')
        return [], []
    with path.open('r', newline='', encoding='utf-8-sig') as stream:
        reader = csv.DictReader(stream)
        return reader.fieldnames or [], list(reader)


def require_columns(headers, required, name):
    missing = [column for column in required if column not in headers]
    if missing:
        raise ValueError(f'{name}: thiếu cột {", ".join(missing)}')


def write_csv_atomic(path, headers, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
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
    forbidden = {'filename', 'source_url_or_archive', 'permission_basis', 'review_notes'}
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
            f'Biểu metadata đang được mở hoặc còn lock cũ: {lock_path}. '
            'Chỉ dùng --force-unlock khi chắc chắn không còn cửa sổ đang chạy.'
        ) from exc
    os.write(descriptor, f'pid={os.getpid()}\nutc={datetime.now(timezone.utc).isoformat()}\n'.encode('utf-8'))
    os.close(descriptor)
    return lock_path


def release_lock(lock_path):
    if lock_path and lock_path.exists():
        lock_path.unlink()


def validate_form_values(values, approving=False):
    status = values.get('review_status', '').strip().lower()
    if status not in ('', 'needs_review', 'approved'):
        raise ValueError('review_status chỉ được để trống, needs_review hoặc approved.')
    if approving or status == 'approved':
        missing = [field for field in REQUIRED_FOR_APPROVAL if not values.get(field, '').strip()]
        if missing:
            raise ValueError(f'Chưa thể approve; còn thiếu {", ".join(missing)}.')
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', values['doc_date'].strip()):
            raise ValueError('doc_date phải theo định dạng YYYY-MM-DD.')


def apply_form_values(row, values, approving=False):
    cleaned = {key: str(value).strip() for key, value in values.items()}
    if approving:
        cleaned['review_status'] = 'approved'
    validate_form_values(cleaned, approving=approving)
    for field in [
        'family_id', 'doc_date', 'source_url_or_archive', 'permission_basis',
        'access_level', 'anonymized', 'reviewer_id', 'review_status', 'review_notes',
    ]:
        row[field] = cleaned.get(field, '')
    row['research_status'] = 'METADATA_REVIEW_NOT_GOLD'
    return row


def build_family_suggestions(rows):
    result = defaultdict(list)
    for row in rows:
        a = row['document_id_a']
        b = row['document_id_b']
        score = f'containment={row["containment"]};jaccard={row["jaccard"]}'
        result[a].append(f'{b}|{score}')
        result[b].append(f'{a}|{score}')
    return {key: ' || '.join(values) for key, values in result.items()}


def family_components(family_rows):
    parent = {}

    def find(value):
        parent.setdefault(value, value)
        if parent[value] != value:
            parent[value] = find(parent[value])
        return parent[value]

    def union(a, b):
        root_a = find(a)
        root_b = find(b)
        if root_a != root_b:
            parent[root_b] = root_a

    for row in family_rows:
        union(row['document_id_a'], row['document_id_b'])
    groups = defaultdict(set)
    for value in parent:
        groups[find(value)].add(value)
    return list(groups.values())


def safe_slug(value, limit=42):
    value = unicodedata.normalize('NFKD', str(value).lower())
    value = ''.join(char for char in value if not unicodedata.combining(char))
    value = value.replace('đ', 'd')
    value = re.sub(r'[^a-z0-9]+', '_', value).strip('_')
    return value[:limit] or 'document'


def unique_family_id(row):
    stem = Path(row['filename']).stem
    suffix = hashlib.sha256(row['document_id'].encode('utf-8')).hexdigest()[:8]
    return f'fam_{safe_slug(stem)}_{suffix}'


def group_family_id(document_ids):
    canonical = '\n'.join(sorted(document_ids))
    suffix = hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:12]
    return f'fam_neardup_{suffix}'


def unanimous_approved_value(rows, field):
    values = {
        row[field].strip()
        for row in rows
        if row['review_status'].strip().lower() == 'approved' and row[field].strip()
    }
    if len(values) != 1:
        raise ValueError(f'Không có đúng một giá trị approved thống nhất cho {field}: {sorted(values)}')
    return next(iter(values))


def build_review_rows(manifest_rows, date_rows, family_rows, legacy_rows=None):
    legacy_rows = legacy_rows or []
    verified_dates = {
        row['document_id']: row
        for row in date_rows
        if row.get('review_status', '').strip().lower() in {'verified', 'approved'} and row.get('verified_iso', '').strip()
    }
    legacy = {row['document_id']: row for row in legacy_rows}
    family_suggestions = build_family_suggestions(family_rows)
    output = []
    for manifest in manifest_rows:
        document_id = manifest['document_id']
        current_date = manifest.get('doc_date', '').strip()
        verified = verified_dates.get(document_id, {})
        legacy_row = legacy.get(document_id, {})
        date_suggestion = verified.get('verified_iso', '').strip() or legacy_row.get('proposed_doc_date', '').strip()
        if verified.get('verified_iso', '').strip():
            date_source = verified.get('verification_method', 'verified_date_file')
        elif legacy_row.get('proposed_doc_date', '').strip():
            date_source = legacy_row.get('date_evidence', 'legacy_proposal')
        else:
            date_source = ''
        family_hint = family_suggestions.get(document_id, '')
        legacy_family = legacy_row.get('proposed_family_id', '').strip()
        if legacy_family:
            family_hint = f'{family_hint} || legacy:{legacy_family}'.strip(' |')
        output.append(
            {
                'document_id': document_id,
                'filename': manifest['filename'],
                'file_sha256': manifest['file_sha256'],
                'family_id': manifest.get('family_id', ''),
                'family_suggestions': family_hint,
                'doc_date': current_date or date_suggestion,
                'date_suggestion': date_suggestion,
                'date_suggestion_source': date_source,
                'doc_type': manifest.get('doc_type', ''),
                'source_url_or_archive': manifest.get('source_url_or_archive', ''),
                'permission_basis': manifest.get('permission_basis', ''),
                'access_level': manifest.get('access_level', ''),
                'anonymized': manifest.get('anonymized', ''),
                'reviewer_id': '',
                'review_status': '',
                'review_notes': '',
                'research_status': 'METADATA_REVIEW_NOT_GOLD',
            }
        )
    return output


def prepare(args):
    manifest_path = ROOT / args.manifest
    output_path = ROOT / args.output
    if output_path.exists():
        raise ValueError(f'Không ghi đè review đã tồn tại: {output_path}')
    manifest_headers, manifest_rows = read_csv_rows(manifest_path, required=True)
    require_columns(manifest_headers, ['document_id', 'filename', 'file_sha256'] + EDITABLE_FIELDS, manifest_path.name)
    date_headers, date_rows = read_csv_rows(ROOT / args.date_suggestions)
    if date_rows:
        require_columns(date_headers, ['document_id', 'verified_iso', 'review_status'], args.date_suggestions)
    family_headers, family_rows = read_csv_rows(ROOT / args.family_suggestions)
    if family_rows:
        require_columns(family_headers, ['document_id_a', 'document_id_b', 'containment', 'jaccard'], args.family_suggestions)
    legacy_headers, legacy_rows = read_csv_rows(ROOT / args.legacy_proposals)
    if legacy_rows:
        require_columns(legacy_headers, ['document_id'], args.legacy_proposals)
    rows = build_review_rows(manifest_rows, date_rows, family_rows, legacy_rows)
    write_csv_atomic(output_path, REVIEW_COLUMNS, rows)
    append_audit(
        output_path.with_suffix('.audit.jsonl'),
        {
            'utc': datetime.now(timezone.utc).isoformat(),
            'event_type': 'manifest_metadata_review.prepared',
            'row_count': len(rows),
            'manifest_sha256': sha256(manifest_path),
            'review_sha256': sha256(output_path),
        },
    )
    print(f'Đã tạo biểu review metadata {len(rows)} văn bản: {output_path}')
    print('Chỉ hàng review_status=approved và đủ trường bắt buộc mới được phép apply.')


def validate_review_identity(manifest_rows, review_rows):
    manifest_by_id = {row['document_id']: row for row in manifest_rows}
    review_by_id = {row['document_id']: row for row in review_rows}
    if len(manifest_by_id) != len(manifest_rows) or len(review_by_id) != len(review_rows):
        raise ValueError('document_id bị trùng trong manifest hoặc review.')
    if set(manifest_by_id) != set(review_by_id):
        raise ValueError('Review phải có đúng cùng tập document_id với manifest.')
    for document_id, review in review_by_id.items():
        manifest = manifest_by_id[document_id]
        if review['filename'] != manifest['filename'] or review['file_sha256'] != manifest['file_sha256']:
            raise ValueError(f'Identity filename/hash không khớp: {document_id}')


def apply(args):
    manifest_path = ROOT / args.manifest
    review_path = ROOT / args.output
    manifest_headers, manifest_rows = read_csv_rows(manifest_path, required=True)
    review_headers, review_rows = read_csv_rows(review_path, required=True)
    require_columns(review_headers, REVIEW_COLUMNS, review_path.name)
    validate_review_identity(manifest_rows, review_rows)
    approved = [row for row in review_rows if row['review_status'].strip().lower() == 'approved']
    if not approved:
        raise ValueError('Chưa có hàng review_status=approved để áp dụng.')
    for row in approved:
        missing = [field for field in REQUIRED_FOR_APPROVAL if not row.get(field, '').strip()]
        if missing:
            raise ValueError(f'{row["document_id"]}: hàng approved còn thiếu {", ".join(missing)}')

    backup_root = ROOT / 'evidence' / 'manifest_backups'
    backup_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
    backup = backup_root / f'{manifest_path.stem}_{stamp}{manifest_path.suffix}'
    shutil.copy2(manifest_path, backup)
    before_hash = sha256(manifest_path)
    approved_by_id = {row['document_id']: row for row in approved}
    changed_fields = Counter()
    for manifest in manifest_rows:
        review = approved_by_id.get(manifest['document_id'])
        if not review:
            continue
        for field in EDITABLE_FIELDS:
            value = review[field].strip()
            if manifest.get(field, '') != value:
                changed_fields[field] += 1
                manifest[field] = value
    write_csv_atomic(manifest_path, manifest_headers, manifest_rows)
    append_audit(
        review_path.with_suffix('.audit.jsonl'),
        {
            'utc': datetime.now(timezone.utc).isoformat(),
            'event_type': 'manifest_metadata_review.applied',
            'approved_rows': len(approved),
            'changed_fields': dict(sorted(changed_fields.items())),
            'before_sha256': before_hash,
            'after_sha256': sha256(manifest_path),
            'backup_file': backup.name,
        },
    )
    print(f'Đã áp dụng {len(approved)} hàng metadata; backup: {backup}')
    print(f'Trường thay đổi: {dict(sorted(changed_fields.items()))}')


def autofill(args):
    review_path = ROOT / args.output
    family_path = ROOT / args.family_suggestions
    headers, rows = read_csv_rows(review_path, required=True)
    require_columns(headers, REVIEW_COLUMNS, review_path.name)
    family_headers, family_rows = read_csv_rows(family_path)
    if family_rows:
        require_columns(family_headers, ['document_id_a', 'document_id_b'], family_path.name)

    defaults = {
        field: unanimous_approved_value(rows, field)
        for field in ('permission_basis', 'access_level', 'anonymized', 'reviewer_id')
    }
    by_id = {row['document_id']: row for row in rows}
    if len(by_id) != len(rows):
        raise ValueError('document_id bị trùng trong biểu review.')
    component_family = {}
    for component in family_components(family_rows):
        existing = {by_id[doc_id]['family_id'].strip() for doc_id in component if by_id[doc_id]['family_id'].strip()}
        if len(existing) > 1:
            raise ValueError(f'Component family có nhiều mã hiện hữu: {sorted(existing)}')
        family_id = next(iter(existing)) if existing else group_family_id(component)
        for document_id in component:
            component_family[document_id] = family_id

    backup_root = ROOT / 'evidence' / 'manifest_review_backups'
    backup_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
    backup = backup_root / f'{review_path.stem}_before_autofill_{stamp}{review_path.suffix}'
    shutil.copy2(review_path, backup)
    before_hash = sha256(review_path)
    counts = Counter()
    for row in rows:
        expected_source = f'local_archive:{row["filename"].replace(chr(92), "/")}'
        if not row['source_url_or_archive'].strip() or row['source_url_or_archive'].count('local_archive:') > 1:
            row['source_url_or_archive'] = expected_source
            counts['source_url_or_archive'] += 1
        if not row['family_id'].strip():
            row['family_id'] = component_family.get(row['document_id'], unique_family_id(row))
            counts['family_id'] += 1
        for field, value in defaults.items():
            if not row[field].strip():
                row[field] = value
                counts[field] += 1
        if row['review_status'].strip().lower() != 'approved':
            row['review_status'] = 'needs_review'
            counts['review_status'] += 1
            marker = 'AUTO_PREFILL_NON_GOLD; VERIFY BEFORE APPROVE'
            if marker not in row['review_notes']:
                row['review_notes'] = f'{row["review_notes"]}; {marker}'.strip('; ')
        row['research_status'] = 'METADATA_REVIEW_NOT_GOLD'

    write_csv_atomic(review_path, headers, rows)
    append_audit(
        review_path.with_suffix('.audit.jsonl'),
        {
            'utc': datetime.now(timezone.utc).isoformat(),
            'event_type': 'manifest_metadata_review.autofilled',
            'changed_fields': dict(sorted(counts.items())),
            'family_components': len(family_components(family_rows)),
            'before_sha256': before_hash,
            'after_sha256': sha256(review_path),
            'backup_file': backup.name,
        },
    )
    missing_dates = sum(not row['doc_date'].strip() for row in rows)
    print(f'Đã autofill biểu metadata; backup: {backup}')
    print(f'Thay đổi: {dict(sorted(counts.items()))}')
    print(f'Hàng còn thiếu doc_date: {missing_dates}; mọi hàng autofill mới giữ needs_review.')


def check(args):
    review_path = ROOT / args.output
    headers, rows = read_csv_rows(review_path, required=True)
    require_columns(headers, REVIEW_COLUMNS, review_path.name)
    statuses = Counter(row['review_status'].strip().lower() or 'unreviewed' for row in rows)
    approved = [row for row in rows if row['review_status'].strip().lower() == 'approved']
    incomplete = 0
    for row in approved:
        incomplete += int(any(not row.get(field, '').strip() for field in REQUIRED_FOR_APPROVAL))
    print(f'Rows={len(rows)}; statuses={dict(sorted(statuses.items()))}; approved_incomplete={incomplete}')
    return 1 if incomplete else 0


class MetadataReviewApp:
    def __init__(self, root, review_path, headers, rows, backup_path, lock_path, audit_path, session_id):
        import tkinter as tk
        from tkinter import messagebox, ttk
        from tkinter.scrolledtext import ScrolledText

        self.tk = tk
        self.messagebox = messagebox
        self.ttk = ttk
        self.root = root
        self.review_path = review_path
        self.headers = headers
        self.rows = rows
        self.backup_path = backup_path
        self.lock_path = lock_path
        self.audit_path = audit_path
        self.session_id = session_id
        self.index = self.first_unapproved_index()
        self.dirty = False
        self.previous_policy = None

        root.title('Review metadata SF2026')
        root.geometry('1260x830')
        root.minsize(980, 680)
        root.protocol('WM_DELETE_WINDOW', self.on_close)

        self.status_var = tk.StringVar()
        self.document_var = tk.StringVar()
        self.filename_var = tk.StringVar()
        self.family_var = tk.StringVar()
        self.date_var = tk.StringVar()
        self.source_var = tk.StringVar()
        self.access_var = tk.StringVar()
        self.anonymized_var = tk.StringVar()
        self.reviewer_var = tk.StringVar()
        self.review_status_var = tk.StringVar()

        header = tk.Frame(root, padx=10, pady=8)
        header.pack(fill='x')
        tk.Label(header, textvariable=self.status_var, font=('Segoe UI', 11, 'bold')).pack(side='left')
        tk.Label(header, textvariable=self.document_var).pack(side='right')

        identity = tk.LabelFrame(root, text='Tài liệu (chỉ đọc)', padx=10, pady=6)
        identity.pack(fill='x', padx=10, pady=4)
        tk.Label(identity, text='File:').grid(row=0, column=0, sticky='w')
        tk.Entry(identity, textvariable=self.filename_var, state='readonly').grid(row=0, column=1, sticky='ew', padx=6)
        identity.columnconfigure(1, weight=1)

        suggestions = tk.LabelFrame(root, text='Gợi ý (không tự động áp dụng)', padx=10, pady=6)
        suggestions.pack(fill='x', padx=10, pady=4)
        self.suggestion_text = ScrolledText(suggestions, height=5, wrap='word', font=('Segoe UI', 10), background='#f5f5f5')
        self.suggestion_text.pack(fill='x')
        self.suggestion_text.configure(state='disabled')

        form = tk.LabelFrame(root, text='Metadata người duyệt xác nhận', padx=10, pady=8)
        form.pack(fill='both', expand=True, padx=10, pady=4)
        labels = [
            ('family_id', self.family_var),
            ('doc_date (YYYY-MM-DD)', self.date_var),
            ('source_url_or_archive', self.source_var),
            ('access_level', self.access_var),
            ('anonymized', self.anonymized_var),
            ('reviewer_id', self.reviewer_var),
            ('review_status', self.review_status_var),
        ]
        access_values = sorted({row['access_level'] for row in rows if row['access_level'].strip()} | {'public'})
        anonymized_values = sorted({row['anonymized'] for row in rows if row['anonymized'].strip()} | {'yes', 'no'})
        for row_index, (label, variable) in enumerate(labels):
            tk.Label(form, text=label).grid(row=row_index, column=0, sticky='nw', pady=4)
            if label == 'access_level':
                widget = ttk.Combobox(form, textvariable=variable, values=access_values, state='normal')
            elif label == 'anonymized':
                widget = ttk.Combobox(form, textvariable=variable, values=anonymized_values, state='normal')
            elif label == 'review_status':
                widget = ttk.Combobox(form, textvariable=variable, values=['', 'needs_review', 'approved'], state='readonly')
            else:
                widget = tk.Entry(form, textvariable=variable)
            widget.grid(row=row_index, column=1, sticky='ew', padx=7, pady=4)
            variable.trace_add('write', lambda *_args: self.mark_dirty())

        permission_row = len(labels)
        tk.Label(form, text='permission_basis').grid(row=permission_row, column=0, sticky='nw', pady=4)
        self.permission_text = ScrolledText(form, height=3, wrap='word', font=('Segoe UI', 10))
        self.permission_text.grid(row=permission_row, column=1, sticky='nsew', padx=7, pady=4)
        self.permission_text.bind('<<Modified>>', self.on_text_modified)

        notes_row = permission_row + 1
        tk.Label(form, text='review_notes').grid(row=notes_row, column=0, sticky='nw', pady=4)
        self.notes_text = ScrolledText(form, height=3, wrap='word', font=('Segoe UI', 10))
        self.notes_text.grid(row=notes_row, column=1, sticky='nsew', padx=7, pady=4)
        self.notes_text.bind('<<Modified>>', self.on_text_modified)
        form.columnconfigure(1, weight=1)
        form.rowconfigure(permission_row, weight=1)
        form.rowconfigure(notes_row, weight=1)

        navigation = tk.Frame(root, padx=10, pady=8)
        navigation.pack(fill='x')
        tk.Button(navigation, text='← Trước (PgUp)', command=self.previous).pack(side='left')
        tk.Button(navigation, text='Hàng chưa approved tiếp', command=self.next_unapproved).pack(side='left', padx=6)
        tk.Button(navigation, text='Sao chép chính sách từ hàng trước', command=self.copy_previous_policy).pack(side='left', padx=6)
        tk.Button(navigation, text='Lưu draft (Ctrl+S)', command=self.save_current).pack(side='right')
        tk.Button(navigation, text='Approve & Next (Ctrl+Enter)', command=self.approve_and_next).pack(side='right', padx=6)

        footer = tk.Label(
            root,
            text='Không tự apply vào manifest | source/quyền dùng phải có căn cứ | family suggestions chỉ là heuristic',
            anchor='w', padx=10, pady=4, fg='#555555',
        )
        footer.pack(fill='x')

        root.bind('<Prior>', lambda _event: self.previous())
        root.bind('<Next>', lambda _event: self.save_and_next())
        root.bind('<Control-s>', lambda _event: self.save_current())
        root.bind('<Control-Return>', lambda _event: self.approve_and_next())
        self.show_current()

    def first_unapproved_index(self):
        for index, row in enumerate(self.rows):
            if row['review_status'].strip().lower() != 'approved':
                return index
        return 0

    def set_readonly_text(self, widget, value):
        widget.configure(state='normal')
        widget.delete('1.0', 'end')
        widget.insert('1.0', value or '')
        widget.configure(state='disabled')

    def show_current(self):
        row = self.rows[self.index]
        approved = sum(item['review_status'].strip().lower() == 'approved' for item in self.rows)
        self.status_var.set(f'Hàng {self.index + 1}/{len(self.rows)} | Approved {approved}/{len(self.rows)}')
        self.document_var.set(row['document_id'])
        self.filename_var.set(row['filename'])
        suggestion = (
            f'Family suggestions: {row["family_suggestions"] or "[không có]"}\n'
            f'Date suggestion: {row["date_suggestion"] or "[không có]"}\n'
            f'Date source: {row["date_suggestion_source"] or "[không có]"}\n'
            f'Doc type: {row["doc_type"]}'
        )
        self.set_readonly_text(self.suggestion_text, suggestion)
        self.family_var.set(row['family_id'])
        self.date_var.set(row['doc_date'])
        self.source_var.set(row['source_url_or_archive'])
        self.access_var.set(row['access_level'])
        self.anonymized_var.set(row['anonymized'])
        self.reviewer_var.set(row['reviewer_id'])
        self.review_status_var.set(row['review_status'])
        self.permission_text.delete('1.0', 'end')
        self.permission_text.insert('1.0', row['permission_basis'])
        self.permission_text.edit_modified(False)
        self.notes_text.delete('1.0', 'end')
        self.notes_text.insert('1.0', row['review_notes'])
        self.notes_text.edit_modified(False)
        self.dirty = False

    def mark_dirty(self):
        self.dirty = True

    def on_text_modified(self, event):
        widget = event.widget
        if widget.edit_modified():
            self.dirty = True
            widget.edit_modified(False)

    def values(self):
        return {
            'family_id': self.family_var.get(),
            'doc_date': self.date_var.get(),
            'source_url_or_archive': self.source_var.get(),
            'permission_basis': self.permission_text.get('1.0', 'end-1c'),
            'access_level': self.access_var.get(),
            'anonymized': self.anonymized_var.get(),
            'reviewer_id': self.reviewer_var.get(),
            'review_status': self.review_status_var.get(),
            'review_notes': self.notes_text.get('1.0', 'end-1c'),
        }

    def save_current(self, approving=False):
        row = self.rows[self.index]
        try:
            before_status = row['review_status']
            apply_form_values(row, self.values(), approving=approving)
            write_csv_atomic(self.review_path, self.headers, self.rows)
            append_audit(
                self.audit_path,
                {
                    'utc': datetime.now(timezone.utc).isoformat(),
                    'event_type': 'manifest_metadata_review.saved',
                    'session_id': self.session_id,
                    'document_id': row['document_id'],
                    'reviewer_id': row['reviewer_id'],
                    'before_status': before_status,
                    'after_status': row['review_status'],
                    'field_presence': {
                        field: bool(row[field].strip())
                        for field in REQUIRED_FOR_APPROVAL
                    },
                    'review_sha256_after': sha256(self.review_path),
                },
            )
            self.previous_policy = {
                'permission_basis': row['permission_basis'],
                'access_level': row['access_level'],
                'anonymized': row['anonymized'],
                'reviewer_id': row['reviewer_id'],
            }
            self.dirty = False
            return True
        except Exception as exc:
            self.messagebox.showerror('Không thể lưu', str(exc))
            return False

    def approve_and_next(self):
        if not self.save_current(approving=True):
            return
        self.next_unapproved(skip_save=True)

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

    def next_unapproved(self, skip_save=False):
        if not skip_save and self.dirty and not self.save_current():
            return
        for offset in range(1, len(self.rows) + 1):
            index = (self.index + offset) % len(self.rows)
            if self.rows[index]['review_status'].strip().lower() != 'approved':
                self.index = index
                self.show_current()
                return
        self.messagebox.showinfo('Hoàn thành', 'Tất cả 79 văn bản đã được approved metadata.')

    def copy_previous_policy(self):
        if not self.previous_policy:
            self.messagebox.showinfo('Chưa có dữ liệu', 'Hãy lưu ít nhất một hàng trước khi sao chép chính sách.')
            return
        self.permission_text.delete('1.0', 'end')
        self.permission_text.insert('1.0', self.previous_policy['permission_basis'])
        self.access_var.set(self.previous_policy['access_level'])
        self.anonymized_var.set(self.previous_policy['anonymized'])
        self.reviewer_var.set(self.previous_policy['reviewer_id'])
        self.dirty = True

    def on_close(self):
        if self.dirty and not self.save_current():
            return
        try:
            append_audit(
                self.audit_path,
                {
                    'utc': datetime.now(timezone.utc).isoformat(),
                    'event_type': 'manifest_metadata_review.session_closed',
                    'session_id': self.session_id,
                    'review_sha256': sha256(self.review_path),
                },
            )
        finally:
            release_lock(self.lock_path)
            self.root.destroy()


def launch_gui(args):
    import tkinter as tk

    review_path = ROOT / args.output
    headers, rows = read_csv_rows(review_path, required=True)
    require_columns(headers, REVIEW_COLUMNS, review_path.name)
    lock_path = acquire_lock(review_path, args.force_unlock)
    backup_root = ROOT / 'evidence' / 'manifest_review_backups'
    backup_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
    backup_path = backup_root / f'{review_path.stem}_{stamp}{review_path.suffix}'
    audit_path = review_path.with_suffix('.audit.jsonl')
    try:
        shutil.copy2(review_path, backup_path)
        if sha256(review_path) != sha256(backup_path):
            raise ValueError('Hash backup biểu metadata không khớp.')
        session_id = f'{os.getpid()}_{stamp}'
        append_audit(
            audit_path,
            {
                'utc': datetime.now(timezone.utc).isoformat(),
                'event_type': 'manifest_metadata_review.session_started',
                'session_id': session_id,
                'row_count': len(rows),
                'review_sha256': sha256(review_path),
                'backup_file': backup_path.name,
            },
        )
        root = tk.Tk()
        MetadataReviewApp(root, review_path, headers, rows, backup_path, lock_path, audit_path, session_id)
        root.mainloop()
    finally:
        release_lock(lock_path)


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description='Review/apply metadata manifest có backup và audit.')
    parser.add_argument('command', choices=['prepare', 'check', 'autofill', 'apply', 'gui'])
    parser.add_argument('--manifest', default='data/processed/documents_manifest.csv')
    parser.add_argument('--date-suggestions', default='results/quality/new_document_date_verified.csv')
    parser.add_argument('--family-suggestions', default='results/quality/family_candidate_pairs.csv')
    parser.add_argument('--legacy-proposals', default='results/quality/manifest_metadata_proposals.csv')
    parser.add_argument('--output', default='data/annotations/manifest_metadata_review.csv')
    parser.add_argument('--force-unlock', action='store_true')
    args = parser.parse_args()
    try:
        if args.command == 'prepare':
            prepare(args)
        elif args.command == 'check':
            raise SystemExit(check(args))
        elif args.command == 'autofill':
            autofill(args)
        elif args.command == 'apply':
            apply(args)
        else:
            launch_gui(args)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(f'LỖI: {exc}') from exc


if __name__ == '__main__':
    main()
