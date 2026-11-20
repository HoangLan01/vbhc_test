import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / 'scripts' / 'build_pilot_units.py'
SPEC = importlib.util.spec_from_file_location('sf2026_pilot_units', SCRIPT_PATH)
units = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(units)


def annotation(segment_id, task, commune, document_id='d1'):
    return {
        'document_id': document_id,
        'segment_id': segment_id,
        'task_present': task,
        'commune_relevance': commune,
    }


class PilotUnitsTests(unittest.TestCase):
    def setUp(self):
        self.context = [
            dict(document_id='d1', segment_id='s1', source_location='page:1/block:1', segment_text='Không nhiệm vụ'),
            dict(document_id='d1', segment_id='s2', source_location='page:1/block:2', segment_text='Giao'),
            dict(document_id='d1', segment_id='s3', source_location='page:1/block:3', segment_text='thực hiện'),
        ]

    def test_builds_consensus_and_pending_merge_units(self):
        a = [annotation('s1', '0', '0'), annotation('s2', '1', '1')]
        b = [annotation('s1', '0', '0'), annotation('s2', '0', '0')]
        adjudication = [
            {
                'document_id': 'd1',
                'segment_id': 's2',
                'unit_status': 'needs_merge',
                'resolved_task_present': '',
                'resolved_commune_relevance': '',
                'member_segment_ids': 's2;s3',
                'adjudicator_id': 'ADJ01',
                'adjudicated_at_utc': '2026-11-19T00:00:00+00:00',
                'adjudication_rationale': 'Câu bị tách',
                'review_status': 'pending_rework',
            }
        ]
        result, mapping = units.build_units(a, b, adjudication, self.context)
        self.assertEqual(len(result), 2)
        consensus = next(row for row in result if row['member_segment_ids'] == 's1')
        merged = next(row for row in result if row['member_segment_ids'] == 's2;s3')
        self.assertEqual(consensus['label_source'], 'a_b_agreement')
        self.assertEqual((consensus['task_present'], consensus['commune_relevance']), ('0', '0'))
        self.assertEqual(merged['label_status'], 'pending_merged_review')
        self.assertEqual(merged['unit_text'], 'Giao thực hiện')
        self.assertEqual(len(mapping), 3)

    def test_adjudicated_identity_overrides_disagreement(self):
        a = [annotation('s1', '0', '0')]
        b = [annotation('s1', '1', '1')]
        adjudication = [
            {
                'document_id': 'd1',
                'segment_id': 's1',
                'unit_status': 'valid',
                'resolved_task_present': '1',
                'resolved_commune_relevance': '0',
                'member_segment_ids': 's1',
                'adjudicator_id': 'ADJ01',
                'adjudicated_at_utc': '2026-11-19T00:00:00+00:00',
                'adjudication_rationale': 'Đã xem toàn văn',
                'review_status': 'draft_adjudicated',
            }
        ]
        result, _ = units.build_units(a, b, adjudication, self.context[:1])
        self.assertEqual(result[0]['label_source'], 'adjudicated')
        self.assertEqual((result[0]['task_present'], result[0]['commune_relevance']), ('1', '0'))

    def test_overlapping_merge_groups_are_rejected(self):
        a = [annotation('s1', '0', '0'), annotation('s2', '1', '0')]
        b = [annotation('s1', '0', '0'), annotation('s2', '1', '0')]
        base = {
            'document_id': 'd1',
            'resolved_task_present': '',
            'resolved_commune_relevance': '',
            'adjudicator_id': 'ADJ01',
            'adjudicated_at_utc': '2026-11-19T00:00:00+00:00',
            'adjudication_rationale': 'Ghép',
            'review_status': 'pending_rework',
            'unit_status': 'needs_merge',
        }
        adjudication = [
            dict(base, segment_id='s1', member_segment_ids='s1;s3'),
            dict(base, segment_id='s2', member_segment_ids='s2;s3'),
        ]
        with self.assertRaises(ValueError):
            units.build_units(a, b, adjudication, self.context)

    def test_audit_rejects_text(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'audit.jsonl'
            units.append_audit_event(path, {'event_type': 'prepared', 'unit_id': 'u1'})
            with self.assertRaises(ValueError):
                units.append_audit_event(path, {'unit_text': 'Không ghi'})


if __name__ == '__main__':
    unittest.main()
