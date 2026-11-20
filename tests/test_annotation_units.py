import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / 'scripts' / 'annotate_units.py'
SPEC = importlib.util.spec_from_file_location('sf2026_annotate_units', SCRIPT_PATH)
annotation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(annotation)


class AnnotationUnitTests(unittest.TestCase):
    def test_apply_labels_and_completion(self):
        row = {column: '' for column in annotation.REQUIRED_COLUMNS}
        annotation.apply_labels(row, '0', '1', 'A02', 'Âm tính')
        self.assertEqual((row['task_present'], row['commune_relevance']), ('0', '0'))
        self.assertEqual(row['label_status'], 'draft')
        self.assertTrue(annotation.is_complete(row))

    def test_document_map_preserves_order(self):
        rows = [
            {'document_id': 'd1', 'annotation_unit_id': 'u1'},
            {'document_id': 'd1', 'annotation_unit_id': 'u2'},
            {'document_id': 'd2', 'annotation_unit_id': 'u3'},
        ]
        mapped = annotation.build_document_map(rows)
        self.assertEqual([row['annotation_unit_id'] for row in mapped['d1']], ['u1', 'u2'])

    def test_audit_rejects_full_text(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'audit.jsonl'
            annotation.append_audit(path, {'event_type': 'saved', 'annotation_unit_id': 'u1'})
            payload = json.loads(path.read_text(encoding='utf-8').strip())
            self.assertEqual(payload['annotation_unit_id'], 'u1')
            with self.assertRaises(ValueError):
                annotation.append_audit(path, {'unit_text': 'Không ghi'})


if __name__ == '__main__':
    unittest.main()
