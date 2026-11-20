#!/usr/bin/env python3
"""Tải, kiểm tra và kiểm kê các bộ dữ liệu ngoài đã được pin revision.

Dữ liệu được lưu dưới data/external và không được coi là target gold E1-E5.
Không file pickle/model nào được thực thi.
"""

import argparse
import csv
import hashlib
import json
import os
import shutil
import stat
import sys
import urllib.parse
import urllib.request
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / 'config' / 'external_datasets.json'
EXTERNAL_ROOT = ROOT / 'data' / 'external'
MANIFEST_PATH = EXTERNAL_ROOT / 'external_manifest.json'
USER_AGENT = 'SF2026-Research-Kit/1.0 external-dataset-fetcher'
CHUNK_SIZE = 1024 * 1024
MAX_ZIP_FILES = 100_000
MAX_ZIP_UNCOMPRESSED = 5 * 1024 * 1024 * 1024
MAX_ZIP_MEMBER = 1024 * 1024 * 1024


def configure_utf8_console():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(CHUNK_SIZE):
            digest.update(block)
    return digest.hexdigest()


def read_config(path):
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('schema_version') != 1 or not isinstance(data.get('datasets'), dict):
        raise ValueError('Cấu hình external datasets không hợp lệ.')
    return data


def dataset_keys(config, selected):
    if selected == 'all':
        return list(config['datasets'])
    if selected not in config['datasets']:
        raise ValueError(f'Không có dataset trong cấu hình: {selected}')
    return [selected]


def resolve_url(repo_id, revision, file_path):
    encoded_path = '/'.join(urllib.parse.quote(part) for part in PurePosixPath(file_path).parts)
    return f'https://huggingface.co/datasets/{repo_id}/resolve/{revision}/{encoded_path}?download=true'


def verify_file(path, expected_size, expected_sha256=''):
    if not path.is_file():
        return False, 'missing'
    actual_size = path.stat().st_size
    if expected_size and actual_size != int(expected_size):
        return False, f'size {actual_size} != {expected_size}'
    actual_hash = sha256(path)
    if expected_sha256 and actual_hash.lower() != expected_sha256.lower():
        return False, f'sha256 {actual_hash} != {expected_sha256}'
    return True, actual_hash


def download_atomic(url, destination, expected_size=0, expected_sha256=''):
    destination.parent.mkdir(parents=True, exist_ok=True)
    valid, detail = verify_file(destination, expected_size, expected_sha256)
    if valid:
        print(f'Đã có và hợp lệ: {destination.name}')
        return detail
    if destination.exists():
        raise ValueError(f'File đích đã tồn tại nhưng không hợp lệ: {destination} ({detail})')

    temp = destination.with_name(f'.{destination.name}.{os.getpid()}.download')
    digest = hashlib.sha256()
    downloaded = 0
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=120) as response, temp.open('wb') as output:
            while True:
                block = response.read(CHUNK_SIZE)
                if not block:
                    break
                output.write(block)
                digest.update(block)
                downloaded += len(block)
                if downloaded % (32 * CHUNK_SIZE) < CHUNK_SIZE:
                    print(f'  {destination.name}: {downloaded / (1024 * 1024):.1f} MiB', flush=True)
        actual_hash = digest.hexdigest()
        if expected_size and downloaded != int(expected_size):
            raise ValueError(f'{destination.name}: tải {downloaded} byte, dự kiến {expected_size}.')
        if expected_sha256 and actual_hash.lower() != expected_sha256.lower():
            raise ValueError(f'{destination.name}: SHA256 không khớp; nhận {actual_hash}.')
        os.replace(temp, destination)
        return actual_hash
    finally:
        if temp.exists():
            temp.unlink()


def validate_zip_members(archive):
    infos = archive.infolist()
    if len(infos) > MAX_ZIP_FILES:
        raise ValueError(f'ZIP có quá nhiều thành viên: {len(infos)}')
    total = 0
    for info in infos:
        posix = PurePosixPath(info.filename.replace('\\', '/'))
        if not info.filename or posix.is_absolute() or '..' in posix.parts:
            raise ValueError(f'Đường dẫn ZIP không an toàn: {info.filename!r}')
        if posix.parts and ':' in posix.parts[0]:
            raise ValueError(f'Đường dẫn ZIP có drive: {info.filename!r}')
        mode = info.external_attr >> 16
        if stat.S_ISLNK(mode):
            raise ValueError(f'ZIP chứa symlink: {info.filename!r}')
        if info.file_size > MAX_ZIP_MEMBER:
            raise ValueError(f'Thành viên ZIP quá lớn: {info.filename!r}')
        total += info.file_size
        if total > MAX_ZIP_UNCOMPRESSED:
            raise ValueError('ZIP vượt giới hạn dung lượng giải nén an toàn.')
    return infos, total


def safe_extract_zip(zip_path, output_dir):
    # Hàm được gọi trực tiếp từ unit test và công cụ khác, không chỉ qua main().
    configure_utf8_console()
    if output_dir.exists():
        if any(output_dir.iterdir()):
            print(f'Đã có thư mục giải nén, không ghi đè: {output_dir}')
            return
        output_dir.rmdir()
    staging = output_dir.with_name(f'.{output_dir.name}.{os.getpid()}.extracting')
    if staging.exists():
        raise ValueError(f'Thư mục staging đã tồn tại: {staging}')
    staging.mkdir(parents=True)
    try:
        with zipfile.ZipFile(zip_path) as archive:
            infos, total = validate_zip_members(archive)
            print(f'ZIP an toàn theo kiểm tra cấu trúc: {len(infos)} thành viên, {total / (1024 * 1024):.1f} MiB giải nén.')
            for info in infos:
                relative = PurePosixPath(info.filename.replace('\\', '/'))
                target = staging.joinpath(*relative.parts)
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, target.open('wb') as destination:
                    shutil.copyfileobj(source, destination, length=CHUNK_SIZE)
        os.replace(staging, output_dir)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def inspect_ota(root):
    extracted = root / 'extracted'
    files = [path for path in extracted.rglob('*') if path.is_file()] if extracted.exists() else []
    extensions = Counter(path.suffix.lower() or '<no_extension>' for path in files)
    risky_extensions = {'.pkl', '.pickle', '.pt', '.pth', '.bin', '.exe', '.dll', '.bat', '.cmd', '.ps1'}
    risky = [str(path.relative_to(extracted)) for path in files if path.suffix.lower() in risky_extensions]
    pdfs = list(extracted.rglob('*.pdf')) if extracted.exists() else []
    json_files = list(extracted.rglob('*.json')) if extracted.exists() else []
    pdf_stems = {path.stem for path in pdfs}
    json_stems = {path.stem for path in json_files}
    annotation_entries = 0
    malformed_entries = 0
    parse_errors = 0
    unique_pairs = set()
    unique_organizations = set()
    task_lengths = []
    for path in json_files:
        try:
            payload = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, UnicodeError, json.JSONDecodeError):
            parse_errors += 1
            continue
        if not isinstance(payload, list):
            parse_errors += 1
            continue
        for entry in payload:
            annotation_entries += 1
            if not isinstance(entry, dict) or not isinstance(entry.get('organization'), list) or not isinstance(entry.get('task'), str):
                malformed_entries += 1
                continue
            organizations = tuple(str(value).strip() for value in entry['organization'])
            task = entry['task'].strip()
            if not task or any(not organization for organization in organizations):
                malformed_entries += 1
                continue
            unique_pairs.add((organizations, task))
            unique_organizations.update(organizations)
            task_lengths.append(len(task))
    return {
        'extracted': extracted.exists(),
        'file_count': len(files),
        'extensions': dict(sorted(extensions.items())),
        'pdf_count': extensions.get('.pdf', 0),
        'json_count': extensions.get('.json', 0) + extensions.get('.jsonl', 0),
        'paired_pdf_json_count': len(pdf_stems & json_stems),
        'pdf_without_json': len(pdf_stems - json_stems),
        'json_without_pdf': len(json_stems - pdf_stems),
        'annotation_entries': annotation_entries,
        'unique_organization_task_pairs': len(unique_pairs),
        'unique_organizations': len(unique_organizations),
        'malformed_annotation_entries': malformed_entries,
        'json_parse_errors': parse_errors,
        'task_length_chars': {
            'min': min(task_lengths) if task_lengths else 0,
            'max': max(task_lengths) if task_lengths else 0,
            'mean': round(sum(task_lengths) / len(task_lengths), 2) if task_lengths else 0,
        },
        'risky_files': risky,
    }


def parse_pap_file(path):
    sentences = 0
    tokens = 0
    malformed = 0
    labels = Counter()
    auxiliary_labels = Counter()
    entities = Counter()
    column_counts = Counter()
    inside_sentence = False
    with path.open('r', encoding='utf-8-sig', errors='strict') as stream:
        for line_number, line in enumerate(stream, 1):
            stripped = line.strip()
            if not stripped:
                if inside_sentence:
                    sentences += 1
                    inside_sentence = False
                continue
            parts = stripped.split()
            column_counts[len(parts)] += 1
            if len(parts) < 4:
                malformed += 1
                continue
            # File thực tế có 5 cột dù dataset card mô tả 4 cột.
            # NER BIO nằm ở cột thứ tư; cột thứ năm được kiểm kê riêng và không dùng làm gold.
            label = parts[3]
            if len(parts) >= 5:
                auxiliary_labels[parts[4]] += 1
            labels[label] += 1
            if label.startswith('B-'):
                entities[label[2:]] += 1
            tokens += 1
            inside_sentence = True
    if inside_sentence:
        sentences += 1
    return {
        'sentences': sentences,
        'tokens': tokens,
        'malformed_lines': malformed,
        'column_counts': dict(sorted(column_counts.items())),
        'label_counts': dict(sorted(labels.items())),
        'auxiliary_label_counts': dict(sorted(auxiliary_labels.items())),
        'entity_counts': dict(sorted(entities.items())),
    }


def iter_pap_sentences(path):
    tokens = []
    labels = []
    auxiliary = []
    with path.open('r', encoding='utf-8-sig', errors='strict') as stream:
        for line in stream:
            stripped = line.strip()
            if not stripped:
                if tokens:
                    yield tokens, labels, auxiliary
                    tokens, labels, auxiliary = [], [], []
                continue
            parts = stripped.split()
            if len(parts) < 4:
                raise ValueError(f'Dòng CoNLL không đủ cột trong {path}: {stripped[:120]}')
            tokens.append(parts[0])
            labels.append(parts[3])
            auxiliary.append(parts[4] if len(parts) >= 5 else '')
    if tokens:
        yield tokens, labels, auxiliary


def write_jsonl_atomic(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f'.{path.name}.{os.getpid()}.tmp')
    count = 0
    try:
        with temp.open('w', encoding='utf-8', newline='\n') as stream:
            for record in records:
                stream.write(json.dumps(record, ensure_ascii=False, separators=(',', ':')) + '\n')
                count += 1
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()
    return count


def prepare_ota(root, revision):
    extracted = root / 'extracted'
    prepared = root / 'prepared'
    json_files = sorted(extracted.rglob('*.json'), key=lambda path: path.stem)

    def document_records():
        for annotation_path in json_files:
            pdf_matches = list(extracted.rglob(f'{annotation_path.stem}.pdf'))
            if len(pdf_matches) != 1:
                raise ValueError(f'Không tìm thấy đúng một PDF cho {annotation_path.name}')
            payload = json.loads(annotation_path.read_text(encoding='utf-8'))
            yield {
                'external_document_id': f'ota_{annotation_path.stem}',
                'source_dataset': 'tedbelford/OTA-dataset',
                'source_revision': revision,
                'pdf_path': str(pdf_matches[0].relative_to(ROOT)),
                'annotation_path': str(annotation_path.relative_to(ROOT)),
                'pdf_sha256': sha256(pdf_matches[0]),
                'annotation_sha256': sha256(annotation_path),
                'pair_count': len(payload),
                'research_status': 'EXTERNAL_OTA_NOT_TARGET_GOLD',
            }

    def pair_records():
        for annotation_path in json_files:
            payload = json.loads(annotation_path.read_text(encoding='utf-8'))
            for index, entry in enumerate(payload, 1):
                canonical = json.dumps(
                    {'organization': entry['organization'], 'task': entry['task']},
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(',', ':'),
                )
                yield {
                    'external_document_id': f'ota_{annotation_path.stem}',
                    'pair_index': index,
                    'organizations': entry['organization'],
                    'task': entry['task'],
                    'pair_sha256': hashlib.sha256(canonical.encode('utf-8')).hexdigest(),
                    'source_dataset': 'tedbelford/OTA-dataset',
                    'source_revision': revision,
                    'research_status': 'EXTERNAL_OTA_NOT_TARGET_GOLD',
                }

    document_path = prepared / 'ota_documents.jsonl'
    pair_path = prepared / 'ota_pairs.jsonl'
    document_count = write_jsonl_atomic(document_path, document_records())
    pair_count = write_jsonl_atomic(pair_path, pair_records())
    return {
        'documents_path': str(document_path.relative_to(ROOT)),
        'documents': document_count,
        'pairs_path': str(pair_path.relative_to(ROOT)),
        'pairs': pair_count,
        'documents_sha256': sha256(document_path),
        'pairs_sha256': sha256(pair_path),
    }


def prepare_pap(root, revision):
    raw = root / 'raw'
    prepared = root / 'prepared'
    outputs = {}
    split_names = {
        'train_data.txt': 'train',
        'dev_data.txt': 'dev',
        'test_data.txt': 'test',
    }
    for filename, split in split_names.items():
        source = raw / filename
        destination = prepared / f'{split}.jsonl'

        def records():
            for index, (tokens, labels, auxiliary) in enumerate(iter_pap_sentences(source), 1):
                yield {
                    'sentence_id': f'pap_{split}_{index:06d}',
                    'tokens': tokens,
                    'ner_tags': labels,
                    'auxiliary_tags': auxiliary,
                    'source_dataset': 'Leekien0108/PAP_NER',
                    'source_revision': revision,
                    'research_status': 'EXTERNAL_PAP_NER_NOT_TARGET_GOLD',
                }

        count = write_jsonl_atomic(destination, records())
        outputs[split] = {
            'path': str(destination.relative_to(ROOT)),
            'sentences': count,
            'sha256': sha256(destination),
        }
    return outputs


def prepare(config, selected_keys):
    EXTERNAL_ROOT.mkdir(parents=True, exist_ok=True)
    result = {}
    if 'ota' in selected_keys:
        result['ota'] = prepare_ota(
            EXTERNAL_ROOT / 'ota',
            config['datasets']['ota']['revision'],
        )
    if 'pap_ner' in selected_keys:
        result['pap_ner'] = prepare_pap(
            EXTERNAL_ROOT / 'pap_ner',
            config['datasets']['pap_ner']['revision'],
        )
    path = EXTERNAL_ROOT / 'prepared_manifest.json'
    payload = {
        'schema_version': 1,
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'datasets': result,
        'note': 'Prepared external transfer data; never treat as target E1-E5 gold/test.',
    }
    temp = path.with_name(f'.{path.name}.{os.getpid()}.tmp')
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temp, path)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f'Đã ghi prepared manifest: {path}')
    return result


def inspect_pap(root):
    raw = root / 'raw'
    splits = {}
    for name in ('train_data.txt', 'dev_data.txt', 'test_data.txt'):
        path = raw / name
        if path.is_file():
            splits[name] = parse_pap_file(path)
    return {'splits': splits}


def collect_local_files(config, selected_keys):
    result = {}
    for key in selected_keys:
        spec = config['datasets'][key]
        raw = EXTERNAL_ROOT / key / 'raw'
        records = []
        for item in spec['files']:
            path = raw / item['path']
            if path.is_file():
                records.append({
                    'path': str(path.relative_to(ROOT)),
                    'size': path.stat().st_size,
                    'sha256': sha256(path),
                })
        result[key] = records
    return result


def write_manifest(config, selected_keys, inspections):
    EXTERNAL_ROOT.mkdir(parents=True, exist_ok=True)
    existing = {}
    if MANIFEST_PATH.exists():
        existing = json.loads(MANIFEST_PATH.read_text(encoding='utf-8'))
    datasets = existing.get('datasets', {})
    local_files = collect_local_files(config, selected_keys)
    for key in selected_keys:
        spec = config['datasets'][key]
        datasets[key] = {
            'repo_id': spec['repo_id'],
            'revision': spec['revision'],
            'license': spec['license'],
            'role': spec['role'],
            'research_status': spec['research_status'],
            'local_files': local_files[key],
            'inspection': inspections.get(key, {}),
        }
    payload = {
        'schema_version': 1,
        'updated_utc': datetime.now(timezone.utc).isoformat(),
        'datasets': datasets,
        'note': 'External datasets are not target gold and must not be merged into E1-E5 test labels.',
    }
    temp = MANIFEST_PATH.with_name(f'.{MANIFEST_PATH.name}.{os.getpid()}.tmp')
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temp, MANIFEST_PATH)


def fetch(config, selected_keys, extract_ota=False):
    for key in selected_keys:
        spec = config['datasets'][key]
        raw = EXTERNAL_ROOT / key / 'raw'
        print(f'== {key}: {spec["repo_id"]}@{spec["revision"]} ==')
        for item in spec['files']:
            destination = raw / item['path']
            url = resolve_url(spec['repo_id'], spec['revision'], item['path'])
            digest = download_atomic(url, destination, item.get('size', 0), item.get('sha256', ''))
            print(f'  OK {item["path"]}: sha256={digest}')
    if extract_ota and 'ota' in selected_keys:
        safe_extract_zip(EXTERNAL_ROOT / 'ota' / 'raw' / 'OTA-dataset.zip', EXTERNAL_ROOT / 'ota' / 'extracted')


def inspect(config, selected_keys):
    inspections = {}
    if 'ota' in selected_keys:
        inspections['ota'] = inspect_ota(EXTERNAL_ROOT / 'ota')
    if 'pap_ner' in selected_keys:
        inspections['pap_ner'] = inspect_pap(EXTERNAL_ROOT / 'pap_ner')
    write_manifest(config, selected_keys, inspections)
    print(json.dumps(inspections, ensure_ascii=False, indent=2))
    print(f'Đã ghi manifest: {MANIFEST_PATH}')
    return inspections


def status(config, selected_keys):
    rows = []
    for key in selected_keys:
        spec = config['datasets'][key]
        raw = EXTERNAL_ROOT / key / 'raw'
        for item in spec['files']:
            path = raw / item['path']
            valid, detail = verify_file(path, item.get('size', 0), item.get('sha256', ''))
            rows.append((key, item['path'], 'OK' if valid else 'MISSING/INVALID', detail))
    writer = csv.writer(sys.stdout, lineterminator='\n')
    writer.writerow(['dataset', 'file', 'status', 'detail'])
    writer.writerows(rows)


def main():
    configure_utf8_console()
    parser = argparse.ArgumentParser(description='Quản lý các bộ dữ liệu ngoài của SF2026.')
    parser.add_argument('--config', default=str(DEFAULT_CONFIG))
    subparsers = parser.add_subparsers(dest='command', required=True)
    for name in ('fetch', 'inspect', 'prepare', 'status'):
        command = subparsers.add_parser(name)
        command.add_argument('--dataset', choices=['all', 'ota', 'pap_ner'], default='all')
        if name == 'fetch':
            command.add_argument('--extract-ota', action='store_true')
    args = parser.parse_args()
    config = read_config(Path(args.config))
    selected = dataset_keys(config, args.dataset)
    if args.command == 'fetch':
        fetch(config, selected, extract_ota=args.extract_ota)
        inspect(config, selected)
    elif args.command == 'inspect':
        inspect(config, selected)
    elif args.command == 'prepare':
        prepare(config, selected)
    else:
        status(config, selected)


if __name__ == '__main__':
    main()
