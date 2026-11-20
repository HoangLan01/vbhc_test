import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / 'scripts' / 'annotate_segments.py'
SPEC = importlib.util.spec_from_file_location('sf2026_annotation_ui', SCRIPT_PATH)
annotation_ui = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(annotation_ui)


class AnnotationCoreTests(unittest.TestCase):
    def test_apply_labels_forces_commune_zero_when_task_is_zero(self):
        row = {column: '' for column in annotation_ui.REQUIRED_COLUMNS}
        annotation_ui.apply_labels(row, '0', '1', 'A01', 'Mẫu âm tính')
        self.assertEqual(row['task_present'], '0')
        self.assertEqual(row['commune_relevance'], '0')
        self.assertEqual(row['annotator_id'], 'A01')
        self.assertEqual(row['label_status'], 'draft')
        self.assertTrue(annotation_ui.is_complete(row))

    def test_incomplete_row_is_not_marked_draft(self):
        row = {column: '' for column in annotation_ui.REQUIRED_COLUMNS}
        annotation_ui.apply_labels(row, '1', '', 'A01', '')
        self.assertEqual(row['annotator_id'], '')
        self.assertEqual(row['label_status'], '')
        self.assertFalse(annotation_ui.is_complete(row))

    def test_quick_labels_cover_three_valid_combinations(self):
        expected = {
            'negative': ('0', '0'),
            'task_not_commune': ('1', '0'),
            'task_commune': ('1', '1'),
        }
        for choice, labels in expected.items():
            row = {column: '' for column in annotation_ui.REQUIRED_COLUMNS}
            annotation_ui.apply_quick_label(row, choice, 'A01')
            self.assertEqual((row['task_present'], row['commune_relevance']), labels)
            self.assertTrue(annotation_ui.is_complete(row))

    def test_audit_log_rejects_text_and_does_not_store_notes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'audit.jsonl'
            annotation_ui.append_audit_event(path, {'event_type': 'annotation.saved', 'segment_id': 's1'})
            payload = json.loads(path.read_text(encoding='utf-8').strip())
            self.assertEqual(payload['segment_id'], 's1')
            self.assertNotIn('segment_text', payload)
            with self.assertRaises(ValueError):
                annotation_ui.append_audit_event(path, {'segment_text': 'Không được ghi'})

    def test_context_does_not_cross_document_boundary(self):
        rows = [
            dict(document_id='doc1', segment_id='s1', source_location='page:1', segment_text='Một'),
            dict(document_id='doc1', segment_id='s2', source_location='page:1', segment_text='Hai'),
            dict(document_id='doc2', segment_id='s3', source_location='page:1', segment_text='Ba'),
        ]
        context = annotation_ui.build_context_map(rows)
        self.assertIsNone(context['s1']['previous'])
        self.assertEqual(context['s1']['next']['segment_id'], 's2')
        self.assertEqual(context['s2']['previous']['segment_id'], 's1')
        self.assertIsNone(context['s2']['next'])
        self.assertIsNone(context['s3']['previous'])
        self.assertIsNone(context['s3']['next'])

    def test_atomic_write_backup_and_file_guard(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_path = root / 'segments_annotatorA.csv'
            row = dict(
                document_id='doc1',
                segment_id='s1',
                source_location='page:1',
                segment_text='Đoạn kiểm thử giả.',
                task_present='',
                commune_relevance='',
                annotator_id='',
                label_status='',
                notes='',
            )
            annotation_ui.write_csv_atomic(input_path, annotation_ui.REQUIRED_COLUMNS, [row])
            headers, rows = annotation_ui.read_csv_rows(input_path)
            annotation_ui.validate_annotation_file(input_path, headers, rows)
            backup = annotation_ui.create_session_backup(input_path, root / 'backups')
            self.assertEqual(annotation_ui.sha256(input_path), annotation_ui.sha256(backup))

            gold_path = root / 'segments_gold.csv'
            annotation_ui.write_csv_atomic(gold_path, annotation_ui.REQUIRED_COLUMNS, [row])
            gold_headers, gold_rows = annotation_ui.read_csv_rows(gold_path)
            with self.assertRaises(ValueError):
                annotation_ui.validate_annotation_file(gold_path, gold_headers, gold_rows)

    def test_lock_prevents_two_sessions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'segments_annotatorA.csv'
            path.write_text('fixture', encoding='utf-8')
            lock = annotation_ui.acquire_lock(path)
            try:
                with self.assertRaises(ValueError):
                    annotation_ui.acquire_lock(path)
            finally:
                annotation_ui.release_lock(lock)
            self.assertFalse(lock.exists())


if __name__ == '__main__':
    unittest.main()
