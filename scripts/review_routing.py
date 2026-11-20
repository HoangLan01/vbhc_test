#!/usr/bin/env python3
"""Tạo và ghi nhận review phân luồng có truy vết, không tự sinh gold.

Công cụ kế thừa các ý tưởng an toàn từ GovDoc: gợi ý tách biệt quyết định
cuối, cho phép accept/reroute/abstain/needs-review/out-of-scope và ghi audit.
Nó không đọc dữ liệu ví dụ làm căn cứ, không gọi API/LLM và không sửa
``tasks_gold.csv`` hoặc file prediction nguồn.
"""

import argparse
import csv
import hashlib
import json
import os
import shutil
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DECISIONS = {'accept', 'reroute', 'abstain', 'needs_review', 'out_of_scope'}
REQUIRED_PREDICTION_COLUMNS = [
    'task_id',
    'document_id',
    'method',
    'candidate1',
    'candidate2',
    'score1',
    'score2',
    'abstain',
]
REVIEW_COLUMNS = REQUIRED_PREDICTION_COLUMNS + [
    'model',
    'alpha',
    'threshold',
    'margin',
    'source_prediction_sha256',
    'units_config_sha256',
    'review_decision',
    'final_unit',
    'reviewer_id',
    'reviewed_at_utc',
    'reviewer_rationale',
    'evidence_unit',
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


def append_audit_event(path, payload):
    """Audit chỉ chứa ID/trạng thái/hash, không chép task hoặc lý do chi tiết."""
    forbidden = {'task_text', 'source_text', 'reviewer_rationale', 'evidence_unit'}
    leaked = forbidden.intersection(payload)
    if leaked:
        raise ValueError(f'Audit không được chứa trường nhạy cảm: {", ".join(sorted(leaked))}')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, separators=(',', ':')) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


def require_columns(headers, required, name):
    missing = [column for column in required if column not in headers]
    if missing:
        raise ValueError(f'{name}: thiếu cột {", ".join(missing)}')


def load_units(path):
    if not path.is_file():
        raise ValueError(f'Không tìm thấy cấu hình đơn vị: {path}')
    payload = json.loads(path.read_text(encoding='utf-8'))
    if payload.get('policy_version') == 'CHUA_XAC_NHAN' or not payload.get('units'):
        raise ValueError('config đơn vị chưa được xác nhận; không thể mở review phân luồng.')
    units = {}
    for item in payload['units']:
        unit_id = str(item.get('unit_id', '')).strip()
        if not unit_id:
            raise ValueError('Mỗi đơn vị phải có unit_id.')
        if unit_id in units:
            raise ValueError(f'unit_id bị trùng: {unit_id}')
        if not str(item.get('authority_source', '')).strip():
            raise ValueError(f'Đơn vị {unit_id} thiếu authority_source.')
        units[unit_id] = item
    return payload, units


def validate_unique_ids(rows, column, name):
    values = [str(row.get(column, '')).strip() for row in rows]
    if any(not value for value in values):
        raise ValueError(f'{name}: có {column} trống.')
    duplicates = [value for value, count in Counter(values).items() if count > 1]
    if duplicates:
        raise ValueError(f'{name}: có {len(duplicates)} {column} bị trùng.')


def build_review_rows(prediction_rows, prediction_hash, units_hash, task_ids, unit_ids):
    validate_unique_ids(prediction_rows, 'task_id', 'predictions')
    rows = []
    for prediction in prediction_rows:
        task_id = prediction['task_id'].strip()
        if task_id not in task_ids:
            raise ValueError(f'Prediction có task_id không tồn tại trong tasks: {task_id}')
        for field in ('candidate1', 'candidate2'):
            candidate = prediction.get(field, '').strip()
            if candidate and candidate not in unit_ids:
                raise ValueError(f'{task_id}: {field}={candidate} không có trong config đơn vị.')
        row = {column: prediction.get(column, '') for column in REQUIRED_PREDICTION_COLUMNS}
        for column in ('model', 'alpha', 'threshold', 'margin'):
            row[column] = prediction.get(column, '')
        row.update(
            source_prediction_sha256=prediction_hash,
            units_config_sha256=units_hash,
            review_decision='',
            final_unit='',
            reviewer_id='',
            reviewed_at_utc='',
            reviewer_rationale='',
            evidence_unit='',
            review_status='',
            research_status='HUMAN_ROUTING_REVIEW_NOT_ADJUDICATED_GOLD',
        )
        rows.append(row)
    return rows


def apply_review(row, decision, final_unit, reviewer_id, reviewer_rationale, evidence_unit, unit_ids):
    decision = decision.strip()
    final_unit = final_unit.strip()
    reviewer_id = reviewer_id.strip()
    if decision not in DECISIONS:
        raise ValueError(f'Quyết định không hợp lệ: {decision}')
    if not reviewer_id:
        raise ValueError('Phải có reviewer_id.')
    if decision == 'accept':
        candidate = row.get('candidate1', '').strip()
        if not candidate:
            raise ValueError('Không thể accept khi candidate1 trống.')
        if final_unit and final_unit != candidate:
            raise ValueError('Accept phải giữ nguyên candidate1; dùng reroute nếu chọn đơn vị khác.')
        final_unit = candidate
    elif decision == 'reroute':
        if not final_unit:
            raise ValueError('Reroute phải có final_unit.')
    else:
        if final_unit:
            raise ValueError(f'{decision} không được có final_unit.')
    if final_unit and final_unit not in unit_ids:
        raise ValueError(f'final_unit không có trong config: {final_unit}')
    if decision in {'accept', 'reroute'} and not evidence_unit.strip():
        raise ValueError('Accept/reroute phải ghi căn cứ phân luồng vào evidence_unit.')

    row['review_decision'] = decision
    row['final_unit'] = final_unit
    row['reviewer_id'] = reviewer_id
    row['reviewed_at_utc'] = datetime.now(timezone.utc).isoformat()
    row['reviewer_rationale'] = reviewer_rationale.strip()
    row['evidence_unit'] = evidence_unit.strip()
    row['review_status'] = 'draft_human_review'
    row['research_status'] = 'HUMAN_ROUTING_REVIEW_NOT_ADJUDICATED_GOLD'
    return row


def validate_review_rows(rows, unit_ids):
    validate_unique_ids(rows, 'task_id', 'routing review')
    issues = []
    for index, row in enumerate(rows, 2):
        decision = row.get('review_decision', '').strip()
        if not decision:
            continue
        try:
            candidate_copy = dict(row)
            apply_review(
                candidate_copy,
                decision,
                row.get('final_unit', ''),
                row.get('reviewer_id', ''),
                row.get('reviewer_rationale', ''),
                row.get('evidence_unit', ''),
                unit_ids,
            )
        except ValueError as exc:
            issues.append(f'Dòng {index}: {exc}')
    return issues


def resolve_path(value):
    path = Path(value)
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def prepare_command(args):
    predictions_path = resolve_path(args.predictions)
    tasks_path = resolve_path(args.tasks)
    units_path = resolve_path(args.units)
    output_path = resolve_path(args.output)
    if output_path.exists():
        raise ValueError(f'File đã tồn tại, không ghi đè: {output_path}')

    prediction_headers, prediction_rows = read_csv_rows(predictions_path)
    require_columns(prediction_headers, REQUIRED_PREDICTION_COLUMNS, predictions_path.name)
    task_headers, task_rows = read_csv_rows(tasks_path)
    require_columns(task_headers, ['task_id', 'document_id'], tasks_path.name)
    validate_unique_ids(task_rows, 'task_id', tasks_path.name)
    _, units = load_units(units_path)
    rows = build_review_rows(
        prediction_rows,
        sha256(predictions_path),
        sha256(units_path),
        {row['task_id'].strip() for row in task_rows},
        set(units),
    )
    write_csv_atomic(output_path, REVIEW_COLUMNS, rows)
    audit_path = output_path.with_suffix('.audit.jsonl')
    append_audit_event(
        audit_path,
        {
            'utc': datetime.now(timezone.utc).isoformat(),
            'event_type': 'routing_review.prepared',
            'review_file': output_path.name,
            'row_count': len(rows),
            'prediction_sha256': sha256(predictions_path),
            'units_sha256': sha256(units_path),
            'review_sha256': sha256(output_path),
        },
    )
    print(f'Đã tạo {len(rows)} hàng review draft: {output_path}')
    print('File này chưa phải gold; chỉ adjudication sau đó mới được phép cập nhật tasks_gold.csv.')


def record_command(args):
    review_path = resolve_path(args.review)
    units_path = resolve_path(args.units)
    headers, rows = read_csv_rows(review_path)
    require_columns(headers, REVIEW_COLUMNS, review_path.name)
    _, units = load_units(units_path)
    matches = [row for row in rows if row['task_id'].strip() == args.task_id.strip()]
    if len(matches) != 1:
        raise ValueError(f'Phải tìm thấy đúng một task_id={args.task_id}; hiện có {len(matches)}.')

    backup_root = ROOT / 'evidence' / 'routing_review_backups'
    backup_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
    backup = backup_root / f'{review_path.stem}_{stamp}{review_path.suffix}'
    shutil.copy2(review_path, backup)
    before_hash = sha256(review_path)
    apply_review(
        matches[0],
        args.decision,
        args.final_unit,
        args.reviewer_id,
        args.rationale,
        args.evidence_unit,
        set(units),
    )
    write_csv_atomic(review_path, headers, rows)
    append_audit_event(
        review_path.with_suffix('.audit.jsonl'),
        {
            'utc': datetime.now(timezone.utc).isoformat(),
            'event_type': 'routing_review.recorded',
            'review_file': review_path.name,
            'task_id': args.task_id.strip(),
            'reviewer_id': args.reviewer_id.strip(),
            'decision': args.decision.strip(),
            'final_unit': matches[0]['final_unit'],
            'rationale_present': bool(args.rationale.strip()),
            'evidence_present': bool(args.evidence_unit.strip()),
            'before_sha256': before_hash,
            'after_sha256': sha256(review_path),
            'backup_file': backup.name,
        },
    )
    print(f'Đã lưu review draft cho task_id={args.task_id}; chưa cập nhật gold.')


def check_command(args):
    review_path = resolve_path(args.review)
    units_path = resolve_path(args.units)
    headers, rows = read_csv_rows(review_path)
    require_columns(headers, REVIEW_COLUMNS, review_path.name)
    _, units = load_units(units_path)
    issues = validate_review_rows(rows, set(units))
    counts = Counter(row.get('review_decision', '').strip() or 'unreviewed' for row in rows)
    print(f'File: {review_path}')
    print(f'Tổng hàng: {len(rows)}; trạng thái: {dict(sorted(counts.items()))}')
    if issues:
        for issue in issues:
            print(f'LỖI: {issue}')
        return 1
    print('Review hợp lệ về kỹ thuật; vẫn chưa phải gold nếu chưa adjudication/approved.')
    return 0


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description='Review phân luồng có audit; không tự ghi gold.')
    subparsers = parser.add_subparsers(dest='command', required=True)

    prepare = subparsers.add_parser('prepare')
    prepare.add_argument('--predictions', required=True)
    prepare.add_argument('--tasks', default='data/annotations/tasks_gold.csv')
    prepare.add_argument('--units', default='config/units.json')
    prepare.add_argument('--output', required=True)

    record = subparsers.add_parser('record')
    record.add_argument('--review', required=True)
    record.add_argument('--units', default='config/units.json')
    record.add_argument('--task-id', required=True)
    record.add_argument('--decision', required=True, choices=sorted(DECISIONS))
    record.add_argument('--final-unit', default='')
    record.add_argument('--reviewer-id', required=True)
    record.add_argument('--rationale', default='')
    record.add_argument('--evidence-unit', default='')

    check = subparsers.add_parser('check')
    check.add_argument('--review', required=True)
    check.add_argument('--units', default='config/units.json')

    args = parser.parse_args()
    try:
        if args.command == 'prepare':
            prepare_command(args)
        elif args.command == 'record':
            record_command(args)
        else:
            raise SystemExit(check_command(args))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(f'LỖI: {exc}') from exc


if __name__ == '__main__':
    main()
