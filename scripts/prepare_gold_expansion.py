#!/usr/bin/env python3
"""Chuẩn bị proposal mở rộng gold mà không sửa manifest/segment/gold.

Đầu ra gồm readiness theo tài liệu, gợi ý family gần trùng và annotation-unit
proposals toàn corpus. Pilot approved được tái sử dụng; mọi unit mới chỉ là
proposal/non-gold và các block ngắn được gắn cờ thay vì tự ghép.
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
from itertools import combinations
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UNIT_COLUMNS = [
    'annotation_unit_id', 'document_id', 'source_locations', 'member_segment_ids',
    'member_count', 'unit_text', 'text_length', 'token_count', 'flags',
    'proposal_status', 'eligible_for_expansion', 'task_present',
    'commune_relevance', 'label_status', 'research_status',
]
MAPPING_COLUMNS = [
    'annotation_unit_id', 'document_id', 'member_order', 'segment_id',
    'source_location', 'segment_text_sha256', 'derivation',
]
READINESS_COLUMNS = [
    'document_id', 'segment_count', 'proposed_unit_count', 'short_lt20',
    'short_lt30', 'ocr_rows', 'duplicate_text_rows', 'pilot_approved_units',
    'missing_family_id', 'missing_doc_date', 'missing_source',
    'missing_permission_basis', 'missing_access_level', 'missing_anonymized',
    'metadata_ready', 'eligible_new_units', 'research_status',
]
FAMILY_COLUMNS = [
    'document_id_a', 'document_id_b', 'shared_informative_segments',
    'segments_a', 'segments_b', 'jaccard', 'containment',
    'suggestion_reason', 'review_status', 'research_status',
]


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def text_sha256(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def normalized(value):
    value = unicodedata.normalize('NFKD', str(value).lower())
    value = ''.join(char for char in value if not unicodedata.combining(char))
    value = value.replace('đ', 'd')
    return re.sub(r'\s+', ' ', value).strip()


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
    if any(not value for value in values) or len(values) != len(set(values)):
        raise ValueError(f'{name}: {column} phải đầy đủ và duy nhất.')


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


def stable_unit_id(document_id, segment_id):
    value = f'{document_id}\n{segment_id}'
    return f'UNIT_SEG_{hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]}'


def metadata_ready(record):
    required = [
        'family_id', 'doc_date', 'source_url_or_archive', 'permission_basis',
        'access_level', 'anonymized',
    ]
    return all(str(record.get(column, '')).strip() for column in required)


def unit_flags(text, source_locations, duplicate_count):
    clean = ' '.join(str(text).split())
    flags = []
    if len(clean) < 20:
        flags.append('short_lt20')
    elif len(clean) < 30:
        flags.append('short_lt30')
    if any('/OCR' in value for value in source_locations):
        flags.append('ocr_source')
    if duplicate_count > 1:
        flags.append('duplicate_exact')
    if '|' in clean or '\t' in clean:
        flags.append('table_like')
    if len(clean.split()) <= 1:
        flags.append('single_token')
    return flags


def build_proposals(manifest_rows, segment_rows, approved_units, approved_mapping):
    validate_unique(manifest_rows, 'document_id', 'manifest')
    validate_unique(segment_rows, 'segment_id', 'candidate segments')
    validate_unique(approved_units, 'annotation_unit_id', 'approved pilot units')
    context_by_id = {row['segment_id']: row for row in segment_rows}
    manifest_by_id = {row['document_id']: row for row in manifest_rows}
    if not set(row['document_id'] for row in segment_rows).issubset(manifest_by_id):
        raise ValueError('Có segment có document_id không nằm trong manifest.')

    pilot_mapping_by_unit = defaultdict(list)
    member_to_pilot_unit = {}
    for row in approved_mapping:
        unit_id = row['annotation_unit_id']
        segment_id = row['segment_id']
        if segment_id in member_to_pilot_unit:
            raise ValueError(f'Pilot mapping chồng lấn segment: {segment_id}')
        if segment_id not in context_by_id:
            raise ValueError(f'Pilot mapping có segment không tồn tại: {segment_id}')
        member_to_pilot_unit[segment_id] = unit_id
        pilot_mapping_by_unit[unit_id].append(row)
    approved_by_id = {row['annotation_unit_id']: row for row in approved_units}
    if set(pilot_mapping_by_unit) != set(approved_by_id):
        raise ValueError('Pilot approved units và mapping không khớp annotation_unit_id.')
    for rows in pilot_mapping_by_unit.values():
        rows.sort(key=lambda row: int(row['member_order']))

    normalized_counts = Counter(normalized(row['segment_text']) for row in segment_rows)
    units = []
    mappings = []
    emitted_pilot = set()
    proposed_counts = Counter()
    pilot_counts = Counter()
    eligible_counts = Counter()

    for segment in segment_rows:
        segment_id = segment['segment_id']
        document_id = segment['document_id']
        if segment_id in member_to_pilot_unit:
            unit_id = member_to_pilot_unit[segment_id]
            if unit_id in emitted_pilot:
                continue
            approved = approved_by_id[unit_id]
            member_rows = pilot_mapping_by_unit[unit_id]
            members = [row['segment_id'] for row in member_rows]
            locations = [context_by_id[item]['source_location'] for item in members]
            flags = unit_flags(approved['unit_text'], locations, 1)
            units.append(
                {
                    'annotation_unit_id': unit_id,
                    'document_id': approved['document_id'],
                    'source_locations': ';'.join(locations),
                    'member_segment_ids': ';'.join(members),
                    'member_count': len(members),
                    'unit_text': approved['unit_text'],
                    'text_length': len(approved['unit_text']),
                    'token_count': len(approved['unit_text'].split()),
                    'flags': ';'.join(flags),
                    'proposal_status': 'pilot_approved',
                    'eligible_for_expansion': '0',
                    'task_present': approved['task_present'],
                    'commune_relevance': approved['commune_relevance'],
                    'label_status': approved['label_status'],
                    'research_status': 'PILOT_APPROVED_REUSED_IN_UNIT_PROPOSALS',
                }
            )
            for order, item in enumerate(members, 1):
                source = context_by_id[item]
                mappings.append(
                    {
                        'annotation_unit_id': unit_id,
                        'document_id': source['document_id'],
                        'member_order': order,
                        'segment_id': item,
                        'source_location': source['source_location'],
                        'segment_text_sha256': text_sha256(source['segment_text']),
                        'derivation': 'pilot_approved_mapping',
                    }
                )
            emitted_pilot.add(unit_id)
            proposed_counts[approved['document_id']] += 1
            pilot_counts[approved['document_id']] += 1
            continue

        text = ' '.join(segment['segment_text'].split())
        norm = normalized(segment['segment_text'])
        flags = unit_flags(text, [segment['source_location']], normalized_counts[norm])
        status = 'needs_segmentation_review' if 'short_lt20' in flags or 'single_token' in flags else 'identity_proposed'
        ready = metadata_ready(manifest_by_id[document_id])
        eligible = status == 'identity_proposed' and ready
        unit_id = stable_unit_id(document_id, segment_id)
        units.append(
            {
                'annotation_unit_id': unit_id,
                'document_id': document_id,
                'source_locations': segment['source_location'],
                'member_segment_ids': segment_id,
                'member_count': 1,
                'unit_text': text,
                'text_length': len(text),
                'token_count': len(text.split()),
                'flags': ';'.join(flags),
                'proposal_status': status,
                'eligible_for_expansion': '1' if eligible else '0',
                'task_present': '',
                'commune_relevance': '',
                'label_status': '',
                'research_status': 'NON_GOLD_ANNOTATION_UNIT_PROPOSAL',
            }
        )
        mappings.append(
            {
                'annotation_unit_id': unit_id,
                'document_id': document_id,
                'member_order': 1,
                'segment_id': segment_id,
                'source_location': segment['source_location'],
                'segment_text_sha256': text_sha256(segment['segment_text']),
                'derivation': 'identity_proposal',
            }
        )
        proposed_counts[document_id] += 1
        if eligible:
            eligible_counts[document_id] += 1

    validate_unique(units, 'annotation_unit_id', 'unit proposals')
    mapped_segments = [row['segment_id'] for row in mappings]
    if len(mapped_segments) != len(set(mapped_segments)) or set(mapped_segments) != set(context_by_id):
        raise ValueError('Mapping proposals phải bao phủ mỗi segment đúng một lần.')

    duplicate_rows = Counter()
    short_lt20 = Counter()
    short_lt30 = Counter()
    ocr_rows = Counter()
    segment_counts = Counter(row['document_id'] for row in segment_rows)
    for row in segment_rows:
        doc_id = row['document_id']
        length = len(' '.join(row['segment_text'].split()))
        short_lt20[doc_id] += int(length < 20)
        short_lt30[doc_id] += int(length < 30)
        ocr_rows[doc_id] += int('/OCR' in row['source_location'])
        duplicate_rows[doc_id] += int(normalized_counts[normalized(row['segment_text'])] > 1)

    readiness = []
    for manifest in manifest_rows:
        doc_id = manifest['document_id']
        missing = {
            'missing_family_id': int(not manifest['family_id'].strip()),
            'missing_doc_date': int(not manifest['doc_date'].strip()),
            'missing_source': int(not manifest['source_url_or_archive'].strip()),
            'missing_permission_basis': int(not manifest['permission_basis'].strip()),
            'missing_access_level': int(not manifest['access_level'].strip()),
            'missing_anonymized': int(not manifest['anonymized'].strip()),
        }
        readiness.append(
            {
                'document_id': doc_id,
                'segment_count': segment_counts[doc_id],
                'proposed_unit_count': proposed_counts[doc_id],
                'short_lt20': short_lt20[doc_id],
                'short_lt30': short_lt30[doc_id],
                'ocr_rows': ocr_rows[doc_id],
                'duplicate_text_rows': duplicate_rows[doc_id],
                'pilot_approved_units': pilot_counts[doc_id],
                **missing,
                'metadata_ready': '1' if not any(missing.values()) else '0',
                'eligible_new_units': eligible_counts[doc_id],
                'research_status': 'NON_GOLD_EXPANSION_READINESS',
            }
        )
    return units, mappings, readiness


def informative_sets(segment_rows, min_length=30, max_document_frequency=5):
    by_document = defaultdict(set)
    document_frequency = Counter()
    for row in segment_rows:
        text = normalized(row['segment_text'])
        if len(text) < min_length:
            continue
        by_document[row['document_id']].add(text)
    for values in by_document.values():
        document_frequency.update(values)
    filtered = {
        document_id: {value for value in values if document_frequency[value] <= max_document_frequency}
        for document_id, values in by_document.items()
    }
    return filtered


def family_candidates(segment_rows, min_shared=3, min_jaccard=0.15, min_containment=0.30):
    by_document = informative_sets(segment_rows)
    rows = []
    for document_a, document_b in combinations(sorted(by_document), 2):
        values_a = by_document[document_a]
        values_b = by_document[document_b]
        if not values_a or not values_b:
            continue
        shared = len(values_a & values_b)
        union = len(values_a | values_b)
        jaccard = shared / union if union else 0.0
        containment = shared / min(len(values_a), len(values_b))
        if shared < min_shared or (jaccard < min_jaccard and containment < min_containment):
            continue
        rows.append(
            {
                'document_id_a': document_a,
                'document_id_b': document_b,
                'shared_informative_segments': shared,
                'segments_a': len(values_a),
                'segments_b': len(values_b),
                'jaccard': round(jaccard, 6),
                'containment': round(containment, 6),
                'suggestion_reason': 'near_duplicate_text_overlap',
                'review_status': '',
                'research_status': 'NON_GOLD_FAMILY_SUGGESTION',
            }
        )
    rows.sort(key=lambda row: (-row['containment'], -row['jaccard'], -row['shared_informative_segments']))
    return rows


def prepare(args):
    paths = {
        'manifest': ROOT / args.manifest,
        'segments': ROOT / args.segments,
        'approved_units': ROOT / args.approved_units,
        'approved_mapping': ROOT / args.approved_mapping,
    }
    outputs = {
        'readiness': ROOT / args.readiness_output,
        'families': ROOT / args.family_output,
        'units': ROOT / args.units_output,
        'mapping': ROOT / args.mapping_output,
        'manifest': ROOT / args.proposals_manifest,
    }
    existing = [path for path in outputs.values() if path.exists()]
    backup_dir = None
    if existing and not args.refresh:
        raise ValueError(f'Không ghi đè output đã tồn tại: {", ".join(str(path) for path in existing)}')
    if existing and args.refresh:
        stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
        backup_dir = ROOT / 'evidence' / 'gold_expansion_backups' / stamp
        backup_dir.mkdir(parents=True)
        for path in existing:
            destination = backup_dir / path.relative_to(ROOT)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
            if sha256(path) != sha256(destination):
                raise ValueError(f'Hash backup output G0 không khớp: {path}')
    manifest_headers, manifest_rows = read_csv_rows(paths['manifest'])
    segment_headers, segment_rows = read_csv_rows(paths['segments'])
    approved_headers, approved_rows = read_csv_rows(paths['approved_units'])
    mapping_headers, approved_mapping = read_csv_rows(paths['approved_mapping'])
    require_columns(manifest_headers, ['document_id', 'family_id', 'doc_date', 'source_url_or_archive', 'permission_basis', 'access_level', 'anonymized'], 'manifest')
    require_columns(segment_headers, ['document_id', 'segment_id', 'source_location', 'segment_text'], 'segments')
    require_columns(approved_headers, ['annotation_unit_id', 'document_id', 'unit_text', 'task_present', 'commune_relevance', 'label_status'], 'approved units')
    require_columns(mapping_headers, ['annotation_unit_id', 'document_id', 'member_order', 'segment_id', 'source_location'], 'approved mapping')

    units, mappings, readiness = build_proposals(manifest_rows, segment_rows, approved_rows, approved_mapping)
    families = family_candidates(segment_rows)
    write_csv_atomic(outputs['readiness'], READINESS_COLUMNS, readiness)
    write_csv_atomic(outputs['families'], FAMILY_COLUMNS, families)
    write_csv_atomic(outputs['units'], UNIT_COLUMNS, units)
    write_csv_atomic(outputs['mapping'], MAPPING_COLUMNS, mappings)
    status_counts = Counter(row['proposal_status'] for row in units)
    payload = {
        'schema_version': 1,
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'research_status': 'NON_GOLD_EXPANSION_PROPOSALS',
        'source_hashes': {key: sha256(path) for key, path in paths.items()},
        'document_count': len(manifest_rows),
        'segment_count': len(segment_rows),
        'unit_proposal_count': len(units),
        'mapping_count': len(mappings),
        'family_candidate_pairs': len(families),
        'metadata_ready_documents': sum(row['metadata_ready'] == '1' for row in readiness),
        'eligible_new_units': sum(int(row['eligible_for_expansion']) for row in units),
        'proposal_status_counts': dict(sorted(status_counts.items())),
        'notes': [
            'Unit proposals are non-gold and do not modify candidate_segments.',
            'Family pairs are heuristic suggestions requiring human review.',
            'Short blocks are flagged, not automatically merged.',
        ],
        'previous_outputs_backup': str(backup_dir.relative_to(ROOT)).replace('\\', '/') if backup_dir else None,
    }
    write_json_atomic(outputs['manifest'], payload)
    print(f'Tài liệu={payload["document_count"]}; segment={payload["segment_count"]}; unit proposals={payload["unit_proposal_count"]}.')
    print(f'Mapping={payload["mapping_count"]}; family suggestions={payload["family_candidate_pairs"]}.')
    print(f'Metadata-ready documents={payload["metadata_ready_documents"]}; eligible new units={payload["eligible_new_units"]}.')
    print(f'Trạng thái unit: {payload["proposal_status_counts"]}')


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description='Tạo proposal mở rộng gold không phá hủy.')
    parser.add_argument('--manifest', default='data/processed/documents_manifest.csv')
    parser.add_argument('--segments', default='data/processed/candidate_segments.csv')
    parser.add_argument('--approved-units', default='data/annotations/pilot_units_approved.csv')
    parser.add_argument('--approved-mapping', default='data/annotations/pilot_unit_mapping.csv')
    parser.add_argument('--readiness-output', default='results/quality/gold_expansion_readiness.csv')
    parser.add_argument('--family-output', default='results/quality/family_candidate_pairs.csv')
    parser.add_argument('--units-output', default='data/annotations/annotation_unit_proposals.csv')
    parser.add_argument('--mapping-output', default='data/annotations/annotation_unit_mapping_proposals.csv')
    parser.add_argument('--proposals-manifest', default='data/annotations/annotation_unit_proposals_manifest.json')
    parser.add_argument('--refresh', action='store_true', help='Backup output hiện có rồi tái tạo từ nguồn mới.')
    args = parser.parse_args()
    try:
        prepare(args)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(f'LỖI: {exc}') from exc


if __name__ == '__main__':
    main()
