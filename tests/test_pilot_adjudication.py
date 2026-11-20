import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / 'scripts' / 'adjudicate_pilot.py'
SPEC = importlib.util.spec_from_file_location('sf2026_pilot_adjudication', SCRIPT_PATH)
adjudication = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adjudication)


def annotation_row(segment_id, task, commune, notes='', document_id='d1'):
    return {
        'document_id': document_id,
        'segment_id': segment_id,
        'source_location': 'page:1/block:1',
        'segment_text': 'fixture',
        'task_present': task,
        'commune_relevance': commune,
        'annotator_id': 'X',
        'label_status': 'draft',
        'notes': notes,
    }


class PilotAdjudicationTests(unittest.TestCase):
    def setUp(self):
        self.context = [
            dict(document_id='d1', segment_id='s1', source_location='page:1/block:1', segment_text='Một'),
            dict(document_id='d1', segment_id='s2', source_location='page:1/block:2', segment_text='Hai'),
            dict(document_id='d2', segment_id='s3', source_location='page:1/block:1', segment_text='Ba'),
        ]
        self.context_by_id = {row['segment_id']: row for row in self.context}

    def test_mandatory_queue_is_union_of_conflict_and_structural_notes(self):
        a = [
            annotation_row('s1', '0', '0'),
            annotation_row('s2', '1', '0', '[SEG_TOO_SHORT] Cần ghép'),
            annotation_row('s3', '0', '0', '[HEADER_FOOTER] Tiêu đề', document_id='d2'),
        ]
        b = [
            annotation_row('s1', '1', '0'),
            annotation_row('s2', '1', '0'),
            annotation_row('s3', '0', '0', document_id='d2'),
        ]
        conflicts = [dict(segment_id='s1', field='task_present', label_a='0', label_b='1')]
        rows = adjudication.build_queue(a, b, conflicts, mode='mandatory')
        self.assertEqual([row['segment_id'] for row in rows], ['s1', 's2'])
        self.assertEqual(rows[0]['review_reason'], 'conflict')
        self.assertIn('structural_note', rows[1]['review_reason'])
        self.assertNotIn('segment_text', rows[0])

    def test_valid_resolution_forces_commune_zero_for_negative(self):
        row = adjudication.build_queue(
            [annotation_row('s1', '0', '0')],
            [annotation_row('s1', '1', '1')],
            [dict(segment_id='s1', field='task_present', label_a='0', label_b='1')],
            mode='mandatory',
        )[0]
        adjudication.apply_adjudication(row, 'valid', '0', '1', 's1', 'ADJ01', 'Âm tính', self.context_by_id)
        self.assertEqual(row['resolved_task_present'], '0')
        self.assertEqual(row['resolved_commune_relevance'], '0')
        self.assertEqual(row['review_status'], 'draft_adjudicated')

    def test_needs_merge_requires_same_document_mapping(self):
        row = adjudication.build_queue(
            [annotation_row('s1', '1', '0', '[MERGE_NEXT]')],
            [annotation_row('s1', '1', '0')],
            [],
            mode='mandatory',
        )[0]
        with self.assertRaises(ValueError):
            adjudication.apply_adjudication(row, 'needs_merge', '', '', 's1', 'ADJ01', '', self.context_by_id)
        with self.assertRaises(ValueError):
            adjudication.apply_adjudication(row, 'needs_merge', '', '', 's1;s3', 'ADJ01', '', self.context_by_id)
        adjudication.apply_adjudication(row, 'needs_merge', '', '', 's1;s2', 'ADJ01', 'Câu bị tách', self.context_by_id)
        self.assertEqual(row['member_segment_ids'], 's1;s2')
        self.assertEqual(row['review_status'], 'pending_rework')

    def test_short_segment_suffix_is_resolved_within_document(self):
        context = [
            dict(document_id='document_abc', segment_id='document_abc_S0090', source_location='page:1', segment_text='Một'),
            dict(document_id='document_abc', segment_id='document_abc_S0091', source_location='page:1', segment_text='Hai'),
        ]
        context_by_id = {row['segment_id']: row for row in context}
        members = adjudication.validate_member_ids(
            'S0090;S0091',
            'document_abc_S0090',
            'document_abc',
            context_by_id,
        )
        self.assertEqual(members, ['document_abc_S0090', 'document_abc_S0091'])

    def test_full_document_map_preserves_context_order(self):
        documents = adjudication.build_document_map(self.context)
        self.assertEqual([row['segment_id'] for row in documents['d1']], ['s1', 's2'])

    def test_audit_rejects_text_and_rationale(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'audit.jsonl'
            adjudication.append_audit_event(path, {'event_type': 'saved', 'segment_id': 's1'})
            payload = json.loads(path.read_text(encoding='utf-8').strip())
            self.assertEqual(payload['segment_id'], 's1')
            with self.assertRaises(ValueError):
                adjudication.append_audit_event(path, {'segment_text': 'Không ghi'})


if __name__ == '__main__':
    unittest.main()
