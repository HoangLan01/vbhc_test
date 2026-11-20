import importlib.util
import csv
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / 'scripts' / 'extract_document_dates.py'
SPEC = importlib.util.spec_from_file_location('sf2026_document_dates', SCRIPT_PATH)
dates = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dates)

APPLY_PATH = Path(__file__).resolve().parents[1] / 'scripts' / 'apply_document_dates.py'
APPLY_SPEC = importlib.util.spec_from_file_location('sf2026_apply_document_dates', APPLY_PATH)
apply_dates = importlib.util.module_from_spec(APPLY_SPEC)
APPLY_SPEC.loader.exec_module(apply_dates)


class DocumentDateTests(unittest.TestCase):
    def test_extracts_vietnamese_and_numeric_dates(self):
        values = dates.dates_from_text('Hà Nội, ngày 18 tháng 11 năm 2026; hạn 20/12/2026')
        self.assertEqual(values, ['2026-11-18', '2026-12-20'])

    def test_rejects_invalid_calendar_date(self):
        self.assertEqual(dates.dates_from_text('ngày 31 tháng 02 năm 2026'), [])

    def test_filename_date_is_only_weak_evidence(self):
        sources = {
            'native_header': [],
            'ocr_psm6': [],
            'ocr_psm11': [],
            'docx_text': [],
            'filename': ['2026-11-13'],
        }
        selected, confidence, _, _ = dates.select_candidate(sources)
        self.assertEqual(selected, '2026-11-13')
        self.assertEqual(confidence, 'filename_only')

    def test_native_and_ocr_agreement_is_high_confidence(self):
        sources = {
            'native_header': ['2026-11-18'],
            'ocr_psm6': ['2026-11-18'],
            'ocr_psm11': [],
            'docx_text': [],
            'filename': [],
        }
        selected, confidence, _, _ = dates.select_candidate(sources)
        self.assertEqual(selected, '2026-11-18')
        self.assertEqual(confidence, 'high')

    def test_apply_verified_dates_preserves_existing_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest = root / 'manifest.csv'
            review = root / 'review.csv'
            manifest_rows = [
                {'document_id': 'old', 'doc_date': '2026-01-01', 'notes': 'keep'},
                {'document_id': 'new', 'doc_date': '', 'notes': 'keep'},
                {'document_id': 'unknown', 'doc_date': '', 'notes': 'keep'},
            ]
            with manifest.open('w', encoding='utf-8-sig', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=['document_id', 'doc_date', 'notes'])
                writer.writeheader()
                writer.writerows(manifest_rows)
            with review.open('w', encoding='utf-8-sig', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=['document_id', 'verified_iso', 'review_status'])
                writer.writeheader()
                writer.writerows([
                    {'document_id': 'old', 'verified_iso': '2026-01-01', 'review_status': 'verified'},
                    {'document_id': 'new', 'verified_iso': '2026-11-18', 'review_status': 'verified'},
                    {'document_id': 'unknown', 'verified_iso': '', 'review_status': 'needs_manual_review'},
                ])
            applied, unresolved, backup = apply_dates.apply_dates(manifest, review, root / 'backups')
            _, rows = apply_dates.read_csv(manifest)
            self.assertEqual(applied, 1)
            self.assertEqual(unresolved, 1)
            self.assertTrue(backup.is_file())
            self.assertEqual(rows[0]['doc_date'], '2026-01-01')
            self.assertEqual(rows[1]['doc_date'], '2026-11-18')
            self.assertEqual(rows[2]['doc_date'], '')
            self.assertTrue(all(row['notes'] == 'keep' for row in rows))


if __name__ == '__main__':
    unittest.main()
