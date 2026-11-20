#!/usr/bin/env python3
"""Chọn batch annotation-unit mở rộng có seed, không sinh nhãn gold.

Master giữ tín hiệu chọn mẫu để audit. Hai biểu A/B chỉ chứa unit nguồn và cột
nhãn trống, không lộ heuristic hoặc nhãn pilot.
"""

import argparse
import csv
import hashlib
import json
import os
import random
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TASK_RX = re.compile(r'\b(giao|yeu cau|de nghi|chu tri|phoi hop|to chuc thuc hien|tham muu|trien khai|bao cao|hoan thanh|ra soat|thuc hien|xay dung ke hoach|tong hop)\b')
COMMUNE_RX = re.compile(r'\b(ubnd cac xa|ubnd cap xa|ubnd xa|ubnd phuong|xa phuong|cap xa|xa va phuong|cac xa|cac phuong)\b')
MASTER_COLUMNS = [
    'batch_order', 'annotation_unit_id', 'document_id', 'source_locations',
    'member_segment_ids', 'unit_text', 'sampling_stratum',
    'heuristic_task_signal', 'heuristic_commune_signal', 'length_bucket',
    'is_duplicate_text', 'is_ocr_source', 'research_status',
]
FORM_COLUMNS = [
    'document_id', 'annotation_unit_id', 'source_locations',
    'member_segment_ids', 'unit_text', 'task_present', 'commune_relevance',
    'annotator_id', 'label_status', 'notes',
]


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


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


def add_features(rows):
    text_counts = Counter(' '.join(row['unit_text'].split()) for row in rows)
    featured = []
    for source in rows:
        row = dict(source)
        text = ' '.join(row['unit_text'].split())
        norm = normalized(text)
        task = int(bool(TASK_RX.search(norm)))
        commune = int(bool(task and COMMUNE_RX.search(norm)))
        length_bucket = 'medium_20_299' if len(text) < 300 else 'long_ge300'
        duplicate = int(text_counts[text] > 1)
        ocr = int('/OCR' in row['source_locations'])
        row.update(
            heuristic_task_signal=task,
            heuristic_commune_signal=commune,
            length_bucket=length_bucket,
            is_duplicate_text=duplicate,
            is_ocr_source=ocr,
            sampling_stratum=f'task{task}_commune{commune}_{length_bucket}_dup{duplicate}_ocr{ocr}',
        )
        featured.append(row)
    return featured


def choose_from_document(rows, quota, rng):
    available = list(rows)
    rng.shuffle(available)
    selected = []
    for signal in (1, 0):
        candidate = next((row for row in available if row['heuristic_task_signal'] == signal), None)
        if candidate and len(selected) < quota:
            selected.append(candidate)
            available.remove(candidate)
    while len(selected) < quota and available:
        selected_strata = Counter(row['sampling_stratum'] for row in selected)
        available.sort(key=lambda row: (selected_strata[row['sampling_stratum']], row['sampling_stratum'], row['annotation_unit_id']))
        selected.append(available.pop(0))
    return selected


def sample_units(rows, n, seed, min_per_document):
    if n <= 0:
        raise ValueError('n phải lớn hơn 0.')
    by_document = defaultdict(list)
    for row in rows:
        by_document[row['document_id']].append(row)
    if not by_document:
        raise ValueError('Không có unit eligible để chọn.')
    minimum_needed = sum(min(min_per_document, len(values)) for values in by_document.values())
    if n < minimum_needed:
        raise ValueError(f'n={n} nhỏ hơn quota tối thiểu thích ứng {minimum_needed}.')
    if n > len(rows):
        raise ValueError(f'n={n} lớn hơn số unit eligible {len(rows)}.')

    rng = random.Random(seed)
    selected = []
    selected_ids = set()
    document_counts = Counter()
    for document_id in sorted(by_document):
        quota = min(min_per_document, len(by_document[document_id]))
        chosen = choose_from_document(by_document[document_id], quota, rng)
        for row in chosen:
            selected.append(row)
            selected_ids.add(row['annotation_unit_id'])
            document_counts[document_id] += 1

    remaining = [row for row in rows if row['annotation_unit_id'] not in selected_ids]
    rng.shuffle(remaining)
    while len(selected) < n:
        selected_task_counts = Counter(row['heuristic_task_signal'] for row in selected)
        selected_strata = Counter(row['sampling_stratum'] for row in selected)
        remaining.sort(
            key=lambda row: (
                selected_task_counts[row['heuristic_task_signal']],
                document_counts[row['document_id']],
                selected_strata[row['sampling_stratum']],
                row['sampling_stratum'],
                row['annotation_unit_id'],
            )
        )
        row = remaining.pop(0)
        selected.append(row)
        selected_ids.add(row['annotation_unit_id'])
        document_counts[row['document_id']] += 1

    rng.shuffle(selected)
    return selected


def build_outputs(selected):
    master = []
    forms = []
    for order, row in enumerate(selected, 1):
        master.append(
            {
                'batch_order': order,
                'annotation_unit_id': row['annotation_unit_id'],
                'document_id': row['document_id'],
                'source_locations': row['source_locations'],
                'member_segment_ids': row['member_segment_ids'],
                'unit_text': row['unit_text'],
                'sampling_stratum': row['sampling_stratum'],
                'heuristic_task_signal': row['heuristic_task_signal'],
                'heuristic_commune_signal': row['heuristic_commune_signal'],
                'length_bucket': row['length_bucket'],
                'is_duplicate_text': row['is_duplicate_text'],
                'is_ocr_source': row['is_ocr_source'],
                'research_status': 'NON_GOLD_SAMPLED_UNIT',
            }
        )
        forms.append(
            {
                'document_id': row['document_id'],
                'annotation_unit_id': row['annotation_unit_id'],
                'source_locations': row['source_locations'],
                'member_segment_ids': row['member_segment_ids'],
                'unit_text': row['unit_text'],
                'task_present': '',
                'commune_relevance': '',
                'annotator_id': '',
                'label_status': '',
                'notes': '',
            }
        )
    return master, forms


def summary_rows(master):
    rows = [
        {'group': 'overall', 'value': 'rows', 'count': len(master)},
        {'group': 'overall', 'value': 'documents', 'count': len({row['document_id'] for row in master})},
    ]
    for field in ('document_id', 'sampling_stratum', 'heuristic_task_signal', 'heuristic_commune_signal', 'length_bucket', 'is_duplicate_text', 'is_ocr_source'):
        counts = Counter(str(row[field]) for row in master)
        for value, count in sorted(counts.items()):
            rows.append({'group': field, 'value': value, 'count': count})
    return rows


def prepare(args):
    paths = {
        'proposals': ROOT / args.proposals,
        'pilot': ROOT / args.pilot_approved,
    }
    outputs = {
        'master': ROOT / args.master,
        'a': ROOT / args.annotator_a,
        'b': ROOT / args.annotator_b,
        'summary': ROOT / args.summary,
        'manifest': ROOT / args.batch_manifest,
    }
    existing = [path for path in outputs.values() if path.exists()]
    if existing:
        raise ValueError(f'Không ghi đè output đã tồn tại: {", ".join(str(path) for path in existing)}')
    proposal_headers, proposals = read_csv_rows(paths['proposals'])
    require_columns(proposal_headers, ['annotation_unit_id', 'document_id', 'source_locations', 'member_segment_ids', 'unit_text', 'eligible_for_expansion'], paths['proposals'].name)
    pilot_headers, pilot = read_csv_rows(paths['pilot'])
    require_columns(pilot_headers, ['annotation_unit_id'], paths['pilot'].name)
    pilot_ids = {row['annotation_unit_id'] for row in pilot}
    eligible = [row for row in proposals if row['eligible_for_expansion'] == '1' and row['annotation_unit_id'] not in pilot_ids]
    featured = add_features(eligible)
    selected = sample_units(featured, args.n, args.seed, args.min_per_document)
    master, forms = build_outputs(selected)
    summary = summary_rows(master)
    write_csv_atomic(outputs['master'], MASTER_COLUMNS, master)
    write_csv_atomic(outputs['a'], FORM_COLUMNS, forms)
    write_csv_atomic(outputs['b'], FORM_COLUMNS, forms)
    write_csv_atomic(outputs['summary'], ['group', 'value', 'count'], summary)
    payload = {
        'schema_version': 1,
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'research_status': 'NON_GOLD_ANNOTATION_BATCH',
        'config': {'n': args.n, 'seed': args.seed, 'min_per_document': args.min_per_document},
        'source_hashes': {key: sha256(path) for key, path in paths.items()},
        'output_hashes': {key: sha256(path) for key, path in outputs.items() if key != 'manifest'},
        'selected_units': len(master),
        'selected_documents': len({row['document_id'] for row in master}),
        'notes': [
            'Master contains heuristic selection signals for audit only.',
            'Annotator forms contain blank labels and no heuristic columns.',
            'Machine selection is not gold.',
        ],
    }
    write_json_atomic(outputs['manifest'], payload)
    print(f'Đã chọn {len(master)} unit từ {payload["selected_documents"]} tài liệu, seed={args.seed}.')
    print(f'Master: {outputs["master"]}')
    print(f'A/B blank: {outputs["a"]}, {outputs["b"]}')


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description='Chọn batch annotation units A/B không sinh gold.')
    parser.add_argument('--proposals', default='data/annotations/annotation_unit_proposals.csv')
    parser.add_argument('--pilot-approved', default='data/annotations/pilot_units_approved.csv')
    parser.add_argument('--n', type=int, default=240)
    parser.add_argument('--seed', type=int, default=43)
    parser.add_argument('--min-per-document', type=int, default=3)
    parser.add_argument('--master', default='data/annotations/gold_batch_01_master.csv')
    parser.add_argument('--annotator-a', default='data/annotations/gold_batch_01_annotatorA.csv')
    parser.add_argument('--annotator-b', default='data/annotations/gold_batch_01_annotatorB.csv')
    parser.add_argument('--summary', default='results/quality/gold_batch_01_summary.csv')
    parser.add_argument('--batch-manifest', default='data/annotations/gold_batch_01_manifest.json')
    args = parser.parse_args()
    try:
        prepare(args)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(f'LỖI: {exc}') from exc


if __name__ == '__main__':
    main()
