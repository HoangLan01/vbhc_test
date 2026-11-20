#!/usr/bin/env python3
"""Khóa pilot v1 bằng bản approved riêng và snapshot SHA-256.

Không sửa A/B, adjudication, mapping hay ``segments_gold.csv``. Snapshot được
ghi dưới ``evidence/pilot_freezes/`` và không ghi đè phiên đã tồn tại.
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
DEFAULT_APPROVED = ROOT / 'data' / 'annotations' / 'pilot_units_approved.csv'
DEFAULT_FREEZE_ROOT = ROOT / 'evidence' / 'pilot_freezes'
SOURCE_PATHS = [
    'data/annotations/pilot_segments.csv',
    'data/annotations/segments_annotatorA.csv',
    'data/annotations/segments_annotatorB.csv',
    'results/metrics/annotation_qc.csv',
    'results/errors/annotation_conflicts.csv',
    'data/annotations/pilot_adjudication.csv',
    'data/annotations/pilot_adjudication.manifest.json',
    'data/annotations/pilot_annotation_units.csv',
    'data/annotations/pilot_unit_mapping.csv',
    'data/annotations/pilot_units_manifest.json',
    'docs/ANNOTATION_GUIDE.md',
    'scripts/annotate_segments.py',
    'scripts/adjudicate_pilot.py',
    'scripts/build_pilot_units.py',
    'scripts/workflow.py',
]
APPROVAL_COLUMNS = ['approval_id', 'approved_by', 'approved_at_utc']


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


def write_json_atomic(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f'.{path.name}.{os.getpid()}.tmp')
    try:
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def validate_units(headers, rows):
    required = [
        'annotation_unit_id', 'document_id', 'member_segment_ids', 'unit_text',
        'task_present', 'commune_relevance', 'label_status', 'research_status',
    ]
    missing = [column for column in required if column not in headers]
    if missing:
        raise ValueError(f'pilot_annotation_units thiếu cột: {", ".join(missing)}')
    ids = [row['annotation_unit_id'].strip() for row in rows]
    if not rows or any(not value for value in ids) or len(ids) != len(set(ids)):
        raise ValueError('annotation_unit_id phải đầy đủ và duy nhất.')
    for index, row in enumerate(rows, 2):
        task = row['task_present']
        commune = row['commune_relevance']
        if task not in ('0', '1') or commune not in ('0', '1'):
            raise ValueError(f'Dòng {index}: nhãn chưa hoàn chỉnh.')
        if task == '0' and commune != '0':
            raise ValueError(f'Dòng {index}: task=0 phải có commune=0.')
        if row['label_status'].startswith('pending'):
            raise ValueError(f'Dòng {index}: còn trạng thái pending.')


def approve_rows(headers, rows, approval_id, approved_by, approved_at):
    validate_units(headers, rows)
    approved = []
    for source in rows:
        row = dict(source)
        row['label_status'] = 'approved_pilot'
        row['research_status'] = 'PILOT_V1_APPROVED_NOT_FULL_CORPUS_GOLD'
        row['approval_id'] = approval_id
        row['approved_by'] = approved_by
        row['approved_at_utc'] = approved_at
        approved.append(row)
    return list(headers) + [column for column in APPROVAL_COLUMNS if column not in headers], approved


def csv_row_count(path):
    if path.suffix.lower() != '.csv':
        return None
    _, rows = read_csv_rows(path)
    return len(rows)


def snapshot_file(root, freeze_dir, source):
    relative = source.relative_to(root)
    destination = freeze_dir / 'snapshot' / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    source_hash = sha256(source)
    if source_hash != sha256(destination):
        raise ValueError(f'Hash snapshot không khớp: {relative}')
    return {
        'source_path': str(relative).replace('\\', '/'),
        'snapshot_path': str(destination.relative_to(freeze_dir)).replace('\\', '/'),
        'sha256': source_hash,
        'size_bytes': source.stat().st_size,
        'row_count': csv_row_count(source),
    }


def freeze(root, approved_path, freeze_root, approval_id, approved_by, source_paths=None, now=None):
    if not approved_by.strip():
        raise ValueError('approved_by không được trống.')
    if approved_path.exists():
        raise ValueError(f'Không ghi đè bản approved đã tồn tại: {approved_path}')
    now = now or datetime.now(timezone.utc)
    approved_at = now.isoformat()
    stamp = now.strftime('%Y%m%d_%H%M%S_%f')
    freeze_dir = freeze_root / f'{approval_id}_{stamp}'
    if freeze_dir.exists():
        raise ValueError(f'Freeze directory đã tồn tại: {freeze_dir}')

    units_path = root / 'data' / 'annotations' / 'pilot_annotation_units.csv'
    headers, rows = read_csv_rows(units_path)
    approved_headers, approved_rows = approve_rows(headers, rows, approval_id, approved_by.strip(), approved_at)
    write_csv_atomic(approved_path, approved_headers, approved_rows)

    requested = source_paths or SOURCE_PATHS
    sources = [root / relative for relative in requested]
    sources.append(approved_path)
    missing = [path for path in sources if not path.is_file()]
    if missing:
        approved_path.unlink(missing_ok=True)
        raise ValueError(f'Thiếu file để freeze: {", ".join(str(path) for path in missing)}')

    try:
        freeze_dir.mkdir(parents=True)
        entries = [snapshot_file(root, freeze_dir, source) for source in sources]
        label_counts = {}
        for row in approved_rows:
            key = f'{row["task_present"]}/{row["commune_relevance"]}'
            label_counts[key] = label_counts.get(key, 0) + 1
        manifest = {
            'schema_version': 1,
            'approval_id': approval_id,
            'approved_by': approved_by.strip(),
            'approved_at_utc': approved_at,
            'research_status': 'PILOT_V1_APPROVED_NOT_FULL_CORPUS_GOLD',
            'unit_count': len(approved_rows),
            'label_counts': dict(sorted(label_counts.items())),
            'files': entries,
        }
        write_json_atomic(freeze_dir / 'freeze_manifest.json', manifest)
        return freeze_dir, manifest
    except Exception:
        if freeze_dir.exists():
            shutil.rmtree(freeze_dir)
        approved_path.unlink(missing_ok=True)
        raise


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description='Khóa pilot approved và snapshot provenance không ghi đè.')
    parser.add_argument('--approval-id', default='pilot_v1')
    parser.add_argument('--approved-by', default='ADJ01')
    parser.add_argument('--approved-output', default=str(DEFAULT_APPROVED.relative_to(ROOT)))
    parser.add_argument('--freeze-root', default=str(DEFAULT_FREEZE_ROOT.relative_to(ROOT)))
    args = parser.parse_args()
    approved_path = (ROOT / args.approved_output).resolve()
    freeze_root = (ROOT / args.freeze_root).resolve()
    try:
        freeze_dir, manifest = freeze(
            ROOT,
            approved_path,
            freeze_root,
            args.approval_id,
            args.approved_by,
        )
        print(f'Đã tạo pilot approved: {approved_path}')
        print(f'Đã khóa snapshot: {freeze_dir}')
        print(f'Units={manifest["unit_count"]}; labels={manifest["label_counts"]}')
        print('Lưu ý: approved pilot không đồng nghĩa gold toàn corpus hoặc kết quả E1–E5.')
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(f'LỖI: {exc}') from exc


if __name__ == '__main__':
    main()
