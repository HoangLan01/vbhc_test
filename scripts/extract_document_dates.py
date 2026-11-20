#!/usr/bin/env python3
"""Trích ứng viên ngày ban hành bằng native text + OCR vùng đầu trang.

Script chỉ tạo báo cáo và ảnh crop; không tự sửa documents_manifest.csv.
"""

import argparse
import csv
import io
import os
import re
import sys
import unicodedata
from collections import defaultdict
from datetime import date
from pathlib import Path

import pymupdf
import pytesseract
from PIL import Image, ImageDraw, ImageFont, ImageOps


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / 'data' / 'processed' / 'documents_manifest.csv'
DEFAULT_OUTPUT = ROOT / 'results' / 'quality' / 'new_document_date_ocr.csv'
DEFAULT_CROPS = ROOT / 'tmp' / 'pdfs' / 'new_document_dates'


def configure_utf8_console():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')


def configure_tesseract():
    if os.name == 'nt' and not Path(pytesseract.pytesseract.tesseract_cmd).is_file():
        candidate = Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'Tesseract-OCR' / 'tesseract.exe'
        if candidate.is_file():
            pytesseract.pytesseract.tesseract_cmd = str(candidate)


def normalized(value):
    value = unicodedata.normalize('NFKD', str(value).lower())
    value = ''.join(char for char in value if not unicodedata.combining(char))
    return re.sub(r'\s+', ' ', value.replace('đ', 'd'))


def valid_iso(day, month, year):
    try:
        return date(int(year), int(month), int(day)).isoformat()
    except ValueError:
        return ''


def dates_from_text(text):
    text_norm = normalized(text)
    found = []
    word_pattern = re.compile(r'\bngay\s*(\d{1,2})\s*thang\s*(\d{1,2})\s*nam\s*((?:19|20)\d{2})\b')
    numeric_pattern = re.compile(r'(?<!\d)(\d{1,2})[./-](\d{1,2})[./-]((?:19|20)\d{2})(?!\d)')
    for pattern in (word_pattern, numeric_pattern):
        for match in pattern.finditer(text_norm):
            iso = valid_iso(match.group(1), match.group(2), match.group(3))
            if iso:
                found.append(iso)
    return list(dict.fromkeys(found))


def dates_from_filename(filename):
    stem = Path(filename).stem
    found = dates_from_text(stem)
    for match in re.finditer(r'(?<!\d)((?:19|20)\d{2})[._-]?(\d{2})[._-]?(\d{2})(?!\d)', stem):
        iso = valid_iso(match.group(3), match.group(2), match.group(1))
        if iso:
            found.append(iso)
    for match in re.finditer(r'(?<!\d)(\d{1,2})[._-](\d{1,2})[._-](\d{2})(?!\d)', stem):
        year = 2000 + int(match.group(3))
        iso = valid_iso(match.group(1), match.group(2), year)
        if iso:
            found.append(iso)
    return list(dict.fromkeys(found))


def extract_docx_text(path):
    from docx import Document

    document = Document(path)
    parts = []
    for section in document.sections:
        parts.extend(paragraph.text for paragraph in section.header.paragraphs)
        for table in section.header.tables:
            parts.extend(cell.text for row in table.rows for cell in row.cells)
    parts.extend(paragraph.text for paragraph in document.paragraphs)
    for table in document.tables:
        parts.extend(cell.text for row in table.rows for cell in row.cells)
    return '\n'.join(parts)


def extract_pdf(path, crop_path, zoom=4.5):
    with pymupdf.open(path) as document:
        page = document[0]
        clip = pymupdf.Rect(0, 0, page.rect.width, page.rect.height * 0.38)
        native = page.get_text('text', clip=clip)
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=clip, alpha=False)
        image = Image.open(io.BytesIO(pixmap.tobytes('png'))).convert('L')
    image = ImageOps.autocontrast(image)
    crop_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(crop_path)
    ocr6 = pytesseract.image_to_string(image, lang='vie+eng', config='--psm 6')
    ocr11 = pytesseract.image_to_string(image, lang='vie+eng', config='--psm 11')
    return native, ocr6, ocr11


def select_candidate(sources):
    scores = defaultdict(int)
    source_map = defaultdict(list)
    weights = {'native_header': 5, 'ocr_psm6': 4, 'ocr_psm11': 3, 'docx_text': 5, 'filename': 1}
    for source, values in sources.items():
        for value in values:
            scores[value] += weights[source]
            source_map[value].append(source)
    if not scores:
        return '', 'none', '', ''
    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    best, best_score = ranked[0]
    tied = len(ranked) > 1 and ranked[1][1] == best_score
    if tied:
        confidence = 'ambiguous'
        selected = ''
    elif best_score >= 5:
        confidence = 'high'
        selected = best
    elif best_score >= 3:
        confidence = 'medium'
        selected = best
    else:
        confidence = 'filename_only'
        selected = best
    all_candidates = ';'.join(f'{value}|score={score}|sources={"+".join(source_map[value])}' for value, score in ranked)
    return selected, confidence, '+'.join(source_map[best]), all_candidates


def create_contact_sheets(records, crops_dir, per_sheet=12):
    font = ImageFont.load_default()
    pdf_records = [record for record in records if record.get('crop_file')]
    outputs = []
    for sheet_index in range(0, len(pdf_records), per_sheet):
        batch = pdf_records[sheet_index:sheet_index + per_sheet]
        tiles = []
        for record in batch:
            image = Image.open(crops_dir / record['crop_file']).convert('RGB')
            image.thumbnail((1100, 260))
            tile = Image.new('RGB', (1120, 310), 'white')
            tile.paste(image, (10, 40))
            label = f'{record["row_number"]:02d} | {Path(record["filename"]).name[:90]} | candidate={record["candidate_iso"] or "?"} | {record["confidence"]}'
            ImageDraw.Draw(tile).text((10, 10), label, fill='black', font=font)
            tiles.append(tile)
        sheet = Image.new('RGB', (1120, 310 * len(tiles)), (230, 230, 230))
        for index, tile in enumerate(tiles):
            sheet.paste(tile, (0, index * 310))
        output = crops_dir / f'contact_{sheet_index // per_sheet + 1:02d}.png'
        sheet.save(output)
        outputs.append(output)
    return outputs


def write_csv_atomic(path, rows, headers):
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


def main():
    configure_utf8_console()
    configure_tesseract()
    parser = argparse.ArgumentParser(description='OCR ứng viên ngày ban hành; không tự sửa manifest.')
    parser.add_argument('--manifest', default=str(DEFAULT_MANIFEST))
    parser.add_argument('--output', default=str(DEFAULT_OUTPUT))
    parser.add_argument('--crops-dir', default=str(DEFAULT_CROPS))
    parser.add_argument('--only-blank', action='store_true')
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    with manifest_path.open(encoding='utf-8-sig', newline='') as stream:
        manifest_rows = list(csv.DictReader(stream))
    selected = [row for row in manifest_rows if not args.only_blank or not row.get('doc_date', '').strip()]
    crops_dir = Path(args.crops_dir)
    records = []
    for row_number, row in enumerate(selected, 1):
        path = ROOT / row['filename']
        sources = {'native_header': [], 'ocr_psm6': [], 'ocr_psm11': [], 'docx_text': [], 'filename': dates_from_filename(path.name)}
        crop_file = ''
        error = ''
        try:
            if path.suffix.lower() == '.pdf':
                crop_file = f'{row_number:02d}_{row["document_id"][:48]}.png'
                native, ocr6, ocr11 = extract_pdf(path, crops_dir / crop_file)
                sources['native_header'] = dates_from_text(native)
                sources['ocr_psm6'] = dates_from_text(ocr6)
                sources['ocr_psm11'] = dates_from_text(ocr11)
            elif path.suffix.lower() == '.docx':
                sources['docx_text'] = dates_from_text(extract_docx_text(path))
            else:
                error = f'Không hỗ trợ metadata date cho {path.suffix}'
        except Exception as exc:
            error = str(exc)
        candidate, confidence, candidate_sources, all_candidates = select_candidate(sources)
        records.append({
            'row_number': row_number,
            'document_id': row['document_id'],
            'filename': row['filename'],
            'candidate_iso': candidate,
            'confidence': confidence,
            'candidate_sources': candidate_sources,
            'all_candidates': all_candidates,
            'crop_file': crop_file,
            'review_status': 'needs_visual_review',
            'verified_iso': '',
            'error': error,
        })
        print(f'[{row_number}/{len(selected)}] {path.name}: {candidate or "?"} ({confidence})')

    headers = list(records[0].keys()) if records else []
    write_csv_atomic(Path(args.output), records, headers)
    sheets = create_contact_sheets(records, crops_dir)
    print(f'Đã ghi {len(records)} hàng: {args.output}')
    print('Contact sheets: ' + ', '.join(str(path) for path in sheets))


if __name__ == '__main__':
    main()
