import importlib.util
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / 'scripts' / 'freeze_pilot.py'
SPEC = importlib.util.spec_from_file_location('sf2026_freeze_pilot', SCRIPT_PATH)
freeze_pilot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(freeze_pilot)


class FreezePilotTests(unittest.TestCase):
    def test_approve_rows_requires_complete_valid_labels(self):
        headers = [
            'annotation_unit_id', 'document_id', 'member_segment_ids', 'unit_text',
            'task_present', 'commune_relevance', 'label_status', 'research_status',
        ]
        row = {
            'annotation_unit_id': 'u1',
            'document_id': 'd1',
            'member_segment_ids': 's1',
            'unit_text': 'fixture',
            'task_present': '1',
            'commune_relevance': '1',
            'label_status': 'draft_consensus',
            'research_status': 'PILOT_DERIVED_UNIT_NOT_GOLD',
        }
        out_headers, approved = freeze_pilot.approve_rows(
            headers,
            [row],
            'pilot_v1',
            'ADJ01',
            '2026-11-19T00:00:00+00:00',
        )
        self.assertIn('approval_id', out_headers)
        self.assertEqual(approved[0]['label_status'], 'approved_pilot')
        self.assertEqual(approved[0]['research_status'], 'PILOT_V1_APPROVED_NOT_FULL_CORPUS_GOLD')

        invalid = dict(row, task_present='0', commune_relevance='1')
        with self.assertRaises(ValueError):
            freeze_pilot.approve_rows(headers, [invalid], 'pilot_v1', 'ADJ01', 'now')

    def test_freeze_creates_snapshot_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            units = root / 'data' / 'annotations' / 'pilot_annotation_units.csv'
            headers = [
                'annotation_unit_id', 'document_id', 'member_segment_ids', 'unit_text',
                'task_present', 'commune_relevance', 'label_status', 'research_status',
            ]
            row = {
                'annotation_unit_id': 'u1', 'document_id': 'd1', 'member_segment_ids': 's1',
                'unit_text': 'fixture', 'task_present': '0', 'commune_relevance': '0',
                'label_status': 'draft_consensus', 'research_status': 'PILOT_DERIVED_UNIT_NOT_GOLD',
            }
            freeze_pilot.write_csv_atomic(units, headers, [row])
            source = root / 'source.txt'
            source.write_text('source', encoding='utf-8')
            approved = root / 'data' / 'annotations' / 'pilot_units_approved.csv'
            freeze_root = root / 'evidence' / 'pilot_freezes'
            now = datetime(2026, 11, 19, tzinfo=timezone.utc)
            freeze_dir, manifest = freeze_pilot.freeze(
                root,
                approved,
                freeze_root,
                'pilot_v1',
                'ADJ01',
                source_paths=['source.txt'],
                now=now,
            )
            self.assertTrue(approved.is_file())
            self.assertTrue((freeze_dir / 'freeze_manifest.json').is_file())
            self.assertEqual(manifest['label_counts'], {'0/0': 1})
            with self.assertRaises(ValueError):
                freeze_pilot.freeze(
                    root,
                    approved,
                    freeze_root,
                    'pilot_v1',
                    'ADJ01',
                    source_paths=['source.txt'],
                    now=now,
                )


if __name__ == '__main__':
    unittest.main()
