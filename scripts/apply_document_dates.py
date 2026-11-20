#!/usr/bin/env python3
"""Áp dụng ngày đã xác minh vào manifest mà không ghi đè ngày hiện có."""

import argparse
import csv
import hashlib
import os
import shutil
import sys
from datetime import date, datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def read_csv(path):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        return reader.fieldnames or [], list(reader)


def valid_iso(value):
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def write_atomic(path, headers, rows):
    temp = path.with_name(f'.{path.name}.{os.getpid()}.tmp')
    try:
        with temp.open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=headers, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def apply_dates(manifest_path, review_path, backup_root):
    headers, manifest = read_csv(manifest_path)
    review_headers, review = read_csv(review_path)
    required_review = {'document_id', 'verified_iso', 'review_status'}
    if not required_review.issubset(review_headers):
        raise ValueError('File review thiếu document_id, verified_iso hoặc review_status.')
    if len({row['document_id'] for row in review}) != len(review):
        raise ValueError('File review có document_id trùng.')
    by_id = {row['document_id']: row for row in manifest}
    applied = 0
    unresolved = 0
    for record in review:
        document_id = record['document_id']
        if document_id not in by_id:
            raise ValueError(f'document_id không có trong manifest: {document_id}')
        value = record['verified_iso'].strip()
        if not value:
            unresolved += 1
            continue
        if record['review_status'] != 'verified':
            raise ValueError(f'Có ngày nhưng chưa verified: {document_id}')
        if not valid_iso(value):
            raise ValueError(f'Ngày không hợp lệ: {document_id}={value}')
        current = by_id[document_id]['doc_date'].strip()
        if current and current != value:
            raise ValueError(f'Không ghi đè ngày hiện có: {document_id}: {current} != {value}')
        if not current:
            by_id[document_id]['doc_date'] = value
            applied += 1

    backup_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
    backup = backup_root / f'{manifest_path.stem}_{stamp}{manifest_path.suffix}'
    shutil.copy2(manifest_path, backup)
    if sha256(manifest_path) != sha256(backup):
        backup.unlink(missing_ok=True)
        raise ValueError('Hash backup manifest không khớp.')
    write_atomic(manifest_path, headers, manifest)
    return applied, unresolved, backup


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description='Áp dụng ngày verified vào documents_manifest.csv.')
    parser.add_argument('--manifest', default=str(ROOT / 'data' / 'processed' / 'documents_manifest.csv'))
    parser.add_argument('--review', default=str(ROOT / 'results' / 'quality' / 'new_document_date_verified.csv'))
    parser.add_argument('--backup-dir', default=str(ROOT / 'evidence' / 'metadata_backups'))
    args = parser.parse_args()
    applied, unresolved, backup = apply_dates(Path(args.manifest), Path(args.review), Path(args.backup_dir))
    print(f'Đã áp dụng {applied} ngày; còn {unresolved} tài liệu cần review.')
    print(f'Backup: {backup}')


if __name__ == '__main__':
    main()
