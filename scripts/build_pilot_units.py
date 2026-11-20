#!/usr/bin/env python3
"""Tạo đơn vị pilot dẫn xuất và mapping mà không sửa segment gốc.

Nguồn gồm biểu A/B, kết quả adjudication và candidate_segments. Đơn vị hợp lệ
được giữ một-một; ``needs_merge`` tạo một annotation_unit_id mới với mapping
đến mọi segment thành viên. Đơn vị ghép để nhãn trống đến khi con người chốt.
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
UNIT_COLUMNS = [
    'annotation_unit_id',
    'document_id',
    'source_locations',
    'member_segment_ids',
    'member_count',
    'unit_text',
    'task_present',
    'commune_relevance',
    'label_source',
    'adjudicator_id',
    'label_status',
    'adjudicated_at_utc',
    'adjudication_rationale',
    'join_strategy',
    'research_status',
]
MAPPING_COLUMNS = [
    'annotation_unit_id',
    'document_id',
    'member_order',
    'segment_id',
    'source_location',
    'segment_text_sha256',
    'derivation',
]


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def text_sha256(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


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
    forbidden = {'unit_text', 'segment_text', 'adjudication_rationale'}
    leaked = forbidden.intersection(payload)
    if leaked:
        raise ValueError(f'Audit không được chứa trường nhạy cảm: {", ".join(sorted(leaked))}')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, separators=(',', ':')) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


def resolve_path(value):
    path = Path(value)
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def unit_id(prefix, document_id, members):
    canonical = json.dumps(
        {'document_id': document_id, 'members': members},
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':'),
    )
    suffix = hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:12]
    return f'PILOT_{prefix}_{suffix}'


def normalize_text(value):
    return ' '.join(str(value).split())


def make_unit(context_by_id, members, labels, metadata, derivation):
    document_ids = {context_by_id[segment_id]['document_id'] for segment_id in members}
    if len(document_ids) != 1:
        raise ValueError('Một annotation unit không được chứa segment thuộc nhiều tài liệu.')
    document_id = next(iter(document_ids))
    prefix = 'MERGE' if derivation == 'merge' else 'SEG'
    annotation_unit_id = unit_id(prefix, document_id, members)
    texts = [normalize_text(context_by_id[segment_id]['segment_text']) for segment_id in members]
    locations = [context_by_id[segment_id]['source_location'] for segment_id in members]
    unit = {
        'annotation_unit_id': annotation_unit_id,
        'document_id': document_id,
        'source_locations': ';'.join(locations),
        'member_segment_ids': ';'.join(members),
        'member_count': len(members),
        'unit_text': ' '.join(text for text in texts if text),
        'task_present': labels.get('task_present', ''),
        'commune_relevance': labels.get('commune_relevance', ''),
        'label_source': metadata.get('label_source', ''),
        'adjudicator_id': metadata.get('adjudicator_id', ''),
        'label_status': metadata.get('label_status', ''),
        'adjudicated_at_utc': metadata.get('adjudicated_at_utc', ''),
        'adjudication_rationale': metadata.get('adjudication_rationale', ''),
        'join_strategy': 'single_space_in_declared_member_order',
        'research_status': 'PILOT_DERIVED_UNIT_NOT_GOLD',
    }
    mappings = []
    for order, segment_id in enumerate(members, 1):
        source = context_by_id[segment_id]
        mappings.append(
            {
                'annotation_unit_id': annotation_unit_id,
                'document_id': document_id,
                'member_order': order,
                'segment_id': segment_id,
                'source_location': source['source_location'],
                'segment_text_sha256': text_sha256(source['segment_text']),
                'derivation': derivation,
            }
        )
    return unit, mappings


def build_units(annotator_a, annotator_b, adjudication, context_rows):
    validate_unique(annotator_a, 'segment_id', 'annotator A')
    validate_unique(annotator_b, 'segment_id', 'annotator B')
    validate_unique(adjudication, 'segment_id', 'adjudication')
    validate_unique(context_rows, 'segment_id', 'candidate segments')
    by_b = {row['segment_id']: row for row in annotator_b}
    if set(by_b) != {row['segment_id'] for row in annotator_a}:
        raise ValueError('Hai biểu A/B không có cùng tập segment_id.')
    context_by_id = {row['segment_id']: row for row in context_rows}
    adjudication_by_id = {row['segment_id']: row for row in adjudication}

    merge_rows = [row for row in adjudication if row['unit_status'] == 'needs_merge']
    merged_members = set()
    for row in merge_rows:
        members = [item.strip() for item in row['member_segment_ids'].split(';') if item.strip()]
        if len(members) < 2 or row['segment_id'] not in members:
            raise ValueError(f'{row["segment_id"]}: mapping merge không hợp lệ.')
        overlap = merged_members.intersection(members)
        if overlap:
            raise ValueError(f'Segment xuất hiện trong nhiều nhóm merge: {", ".join(sorted(overlap))}')
        missing = [segment_id for segment_id in members if segment_id not in context_by_id]
        if missing:
            raise ValueError(f'Mapping chứa segment không có trong context: {", ".join(missing)}')
        merged_members.update(members)

    units = []
    mappings = []
    emitted_merge_owners = set()
    for row_a in annotator_a:
        segment_id = row_a['segment_id']
        if segment_id in merged_members:
            owner = next(
                row for row in merge_rows
                if segment_id in {item.strip() for item in row['member_segment_ids'].split(';') if item.strip()}
            )
            if owner['segment_id'] in emitted_merge_owners:
                continue
            members = [item.strip() for item in owner['member_segment_ids'].split(';') if item.strip()]
            unit, unit_mappings = make_unit(
                context_by_id,
                members,
                {'task_present': '', 'commune_relevance': ''},
                {
                    'label_source': 'pending_merged_review',
                    'adjudicator_id': owner['adjudicator_id'],
                    'label_status': 'pending_merged_review',
                    'adjudicated_at_utc': owner['adjudicated_at_utc'],
                    'adjudication_rationale': owner['adjudication_rationale'],
                },
                'merge',
            )
            units.append(unit)
            mappings.extend(unit_mappings)
            emitted_merge_owners.add(owner['segment_id'])
            continue

        if segment_id not in context_by_id:
            raise ValueError(f'Pilot segment không có trong context: {segment_id}')
        if segment_id in adjudication_by_id:
            resolved = adjudication_by_id[segment_id]
            if resolved['unit_status'] != 'valid':
                unit_status = resolved['unit_status']
                unit, unit_mappings = make_unit(
                    context_by_id,
                    [segment_id],
                    {'task_present': '', 'commune_relevance': ''},
                    {
                        'label_source': unit_status,
                        'adjudicator_id': resolved['adjudicator_id'],
                        'label_status': 'pending_rework',
                        'adjudicated_at_utc': resolved['adjudicated_at_utc'],
                        'adjudication_rationale': resolved['adjudication_rationale'],
                    },
                    'identity',
                )
            else:
                unit, unit_mappings = make_unit(
                    context_by_id,
                    [segment_id],
                    {
                        'task_present': resolved['resolved_task_present'],
                        'commune_relevance': resolved['resolved_commune_relevance'],
                    },
                    {
                        'label_source': 'adjudicated',
                        'adjudicator_id': resolved['adjudicator_id'],
                        'label_status': 'draft_adjudicated',
                        'adjudicated_at_utc': resolved['adjudicated_at_utc'],
                        'adjudication_rationale': resolved['adjudication_rationale'],
                    },
                    'identity',
                )
        else:
            row_b = by_b[segment_id]
            labels_a = (row_a['task_present'], row_a['commune_relevance'])
            labels_b = (row_b['task_present'], row_b['commune_relevance'])
            if labels_a != labels_b:
                raise ValueError(f'Bất đồng chưa adjudication: {segment_id}')
            unit, unit_mappings = make_unit(
                context_by_id,
                [segment_id],
                {'task_present': labels_a[0], 'commune_relevance': labels_a[1]},
                {
                    'label_source': 'a_b_agreement',
                    'label_status': 'draft_consensus',
                },
                'identity',
            )
        units.append(unit)
        mappings.extend(unit_mappings)

    validate_units(units, mappings)
    return units, mappings


def validate_units(units, mappings):
    validate_unique(units, 'annotation_unit_id', 'pilot units')
    member_counts = Counter(row['segment_id'] for row in mappings)
    overlap = [segment_id for segment_id, count in member_counts.items() if count > 1]
    if overlap:
        raise ValueError(f'Segment thuộc nhiều annotation unit: {", ".join(overlap[:5])}')
    mapping_by_unit = Counter(row['annotation_unit_id'] for row in mappings)
    issues = []
    for index, unit in enumerate(units, 2):
        if int(unit['member_count']) != mapping_by_unit[unit['annotation_unit_id']]:
            issues.append(f'Dòng {index}: member_count không khớp mapping.')
        task = unit['task_present']
        commune = unit['commune_relevance']
        if unit['label_status'] == 'pending_merged_review':
            if task or commune:
                issues.append(f'Dòng {index}: đơn vị pending merge phải để nhãn trống.')
        else:
            if task not in ('0', '1') or commune not in ('0', '1'):
                issues.append(f'Dòng {index}: nhãn phải là 0/1.')
            if task == '0' and commune != '0':
                issues.append(f'Dòng {index}: task=0 phải có commune=0.')
    if issues:
        raise ValueError('; '.join(issues[:10]))


def source_manifest(paths, units, mappings):
    return {
        'schema_version': 1,
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'research_status': 'PILOT_DERIVED_UNITS_NOT_GOLD',
        'join_strategy': 'single_space_in_declared_member_order',
        'unit_count': len(units),
        'mapping_count': len(mappings),
        'pending_merged_review': sum(unit['label_status'] == 'pending_merged_review' for unit in units),
        'sources': {
            key: {'path': str(path.relative_to(ROOT)), 'sha256': sha256(path)}
            for key, path in paths.items()
        },
    }


def load_inputs(args):
    paths = {
        'annotator_a': resolve_path(args.annotator_a),
        'annotator_b': resolve_path(args.annotator_b),
        'adjudication': resolve_path(args.adjudication),
        'context': resolve_path(args.context),
    }
    a_headers, a_rows = read_csv_rows(paths['annotator_a'])
    b_headers, b_rows = read_csv_rows(paths['annotator_b'])
    adjudication_headers, adjudication_rows = read_csv_rows(paths['adjudication'])
    context_headers, context_rows = read_csv_rows(paths['context'])
    annotation_columns = ['document_id', 'segment_id', 'task_present', 'commune_relevance']
    require_columns(a_headers, annotation_columns, paths['annotator_a'].name)
    require_columns(b_headers, annotation_columns, paths['annotator_b'].name)
    require_columns(
        adjudication_headers,
        [
            'document_id', 'segment_id', 'unit_status', 'resolved_task_present',
            'resolved_commune_relevance', 'member_segment_ids', 'adjudicator_id',
            'adjudicated_at_utc', 'adjudication_rationale', 'review_status',
        ],
        paths['adjudication'].name,
    )
    require_columns(context_headers, ['document_id', 'segment_id', 'source_location', 'segment_text'], paths['context'].name)
    return paths, a_rows, b_rows, adjudication_rows, context_rows


def prepare_command(args):
    units_path = resolve_path(args.units_output)
    mapping_path = resolve_path(args.mapping_output)
    manifest_path = resolve_path(args.manifest_output)
    audit_path = units_path.with_suffix('.audit.jsonl')
    existing = [path for path in (units_path, mapping_path, manifest_path) if path.exists()]
    if existing:
        raise ValueError(f'Không ghi đè output đã tồn tại: {", ".join(str(path) for path in existing)}')
    paths, a_rows, b_rows, adjudication_rows, context_rows = load_inputs(args)
    units, mappings = build_units(a_rows, b_rows, adjudication_rows, context_rows)
    write_csv_atomic(units_path, UNIT_COLUMNS, units)
    write_csv_atomic(mapping_path, MAPPING_COLUMNS, mappings)
    manifest = source_manifest(paths, units, mappings)
    write_json_atomic(manifest_path, manifest)
    append_audit_event(
        audit_path,
        {
            'utc': datetime.now(timezone.utc).isoformat(),
            'event_type': 'pilot_units.prepared',
            'units_file': units_path.name,
            'mapping_file': mapping_path.name,
            'unit_count': len(units),
            'mapping_count': len(mappings),
            'pending_merged_review': manifest['pending_merged_review'],
            'units_sha256': sha256(units_path),
            'mapping_sha256': sha256(mapping_path),
        },
    )
    print(f'Đã tạo {len(units)} annotation units và {len(mappings)} mapping rows.')
    print(f'Units: {units_path}')
    print(f'Mapping: {mapping_path}')
    print(f'Đơn vị ghép chờ chốt nhãn: {manifest["pending_merged_review"]}')


def check_command(args):
    units_path = resolve_path(args.units_output)
    mapping_path = resolve_path(args.mapping_output)
    manifest_path = resolve_path(args.manifest_output)
    unit_headers, units = read_csv_rows(units_path)
    mapping_headers, mappings = read_csv_rows(mapping_path)
    require_columns(unit_headers, UNIT_COLUMNS, units_path.name)
    require_columns(mapping_headers, MAPPING_COLUMNS, mapping_path.name)
    validate_units(units, mappings)
    if not manifest_path.is_file():
        raise ValueError(f'Thiếu manifest: {manifest_path}')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    pending = [unit for unit in units if unit['label_status'] == 'pending_merged_review']
    status_counts = Counter(unit['label_status'] for unit in units)
    print(f'Units hợp lệ: {len(units)}; mapping rows: {len(mappings)}.')
    print(f'Trạng thái: {dict(sorted(status_counts.items()))}')
    print(f'Chờ chốt nhãn đơn vị ghép: {len(pending)}')
    print(f'Manifest research_status: {manifest.get("research_status")}')
    return 0


def label_command(args):
    units_path = resolve_path(args.units_output)
    mapping_path = resolve_path(args.mapping_output)
    unit_headers, units = read_csv_rows(units_path)
    mapping_headers, mappings = read_csv_rows(mapping_path)
    require_columns(unit_headers, UNIT_COLUMNS, units_path.name)
    require_columns(mapping_headers, MAPPING_COLUMNS, mapping_path.name)
    matches = [unit for unit in units if unit['annotation_unit_id'] == args.unit_id]
    if len(matches) != 1:
        raise ValueError(f'Phải tìm thấy đúng một unit_id={args.unit_id}; hiện có {len(matches)}.')
    unit = matches[0]
    if unit['label_status'] != 'pending_merged_review':
        raise ValueError('Chỉ được dùng lệnh label cho đơn vị pending_merged_review.')
    task = args.task_present
    commune = args.commune_relevance
    if task == '0':
        commune = '0'
    if not args.rationale.strip():
        raise ValueError('Phải có rationale khi chốt đơn vị ghép.')
    if task not in ('0', '1') or commune not in ('0', '1'):
        raise ValueError('Nhãn phải là 0 hoặc 1.')

    backup_root = ROOT / 'evidence' / 'pilot_units_backups'
    backup_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
    backup = backup_root / f'{units_path.stem}_{stamp}{units_path.suffix}'
    shutil.copy2(units_path, backup)
    before_hash = sha256(units_path)
    unit['task_present'] = task
    unit['commune_relevance'] = commune
    unit['label_source'] = 'merged_unit_adjudicated'
    unit['adjudicator_id'] = args.adjudicator_id.strip()
    unit['label_status'] = 'draft_merged_adjudicated'
    unit['adjudicated_at_utc'] = datetime.now(timezone.utc).isoformat()
    unit['adjudication_rationale'] = args.rationale.strip()
    write_csv_atomic(units_path, unit_headers, units)
    validate_units(units, mappings)
    append_audit_event(
        units_path.with_suffix('.audit.jsonl'),
        {
            'utc': datetime.now(timezone.utc).isoformat(),
            'event_type': 'pilot_units.merged_label_recorded',
            'unit_id': args.unit_id,
            'adjudicator_id': args.adjudicator_id.strip(),
            'task_present': task,
            'commune_relevance': commune,
            'rationale_present': True,
            'before_sha256': before_hash,
            'after_sha256': sha256(units_path),
            'backup_file': backup.name,
        },
    )
    print(f'Đã chốt nhãn draft cho đơn vị ghép {args.unit_id}; chưa phải gold.')


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description='Tạo/chốt đơn vị pilot dẫn xuất có mapping và provenance.')
    parser.add_argument('command', choices=['prepare', 'check', 'label'])
    parser.add_argument('--annotator-a', default='data/annotations/segments_annotatorA.csv')
    parser.add_argument('--annotator-b', default='data/annotations/segments_annotatorB.csv')
    parser.add_argument('--adjudication', default='data/annotations/pilot_adjudication.csv')
    parser.add_argument('--context', default='data/processed/candidate_segments.csv')
    parser.add_argument('--units-output', default='data/annotations/pilot_annotation_units.csv')
    parser.add_argument('--mapping-output', default='data/annotations/pilot_unit_mapping.csv')
    parser.add_argument('--manifest-output', default='data/annotations/pilot_units_manifest.json')
    parser.add_argument('--unit-id', default='')
    parser.add_argument('--task-present', choices=['0', '1'])
    parser.add_argument('--commune-relevance', choices=['0', '1'])
    parser.add_argument('--adjudicator-id', default='ADJ01')
    parser.add_argument('--rationale', default='')
    args = parser.parse_args()
    try:
        if args.command == 'prepare':
            prepare_command(args)
        elif args.command == 'check':
            raise SystemExit(check_command(args))
        else:
            if not args.unit_id or args.task_present is None or args.commune_relevance is None:
                raise ValueError('Lệnh label cần --unit-id, --task-present và --commune-relevance.')
            label_command(args)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(f'LỖI: {exc}') from exc


if __name__ == '__main__':
    main()
