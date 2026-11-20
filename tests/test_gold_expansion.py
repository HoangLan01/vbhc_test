import importlib.util
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / 'scripts' / 'prepare_gold_expansion.py'
SPEC = importlib.util.spec_from_file_location('sf2026_gold_expansion', SCRIPT_PATH)
expansion = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(expansion)


class GoldExpansionTests(unittest.TestCase):
    def test_build_proposals_reuses_pilot_mapping_and_covers_segments_once(self):
        manifest = [
            {
                'document_id': 'd1', 'family_id': 'f1', 'doc_date': '2026-01-01',
                'source_url_or_archive': 'archive', 'permission_basis': 'allowed',
                'access_level': 'internal', 'anonymized': 'yes',
            }
        ]
        segments = [
            {'document_id': 'd1', 'segment_id': 's1', 'source_location': 'page:1/block:1', 'segment_text': 'Đoạn đủ dài để làm một đơn vị đề xuất.'},
            {'document_id': 'd1', 'segment_id': 's2', 'source_location': 'page:1/block:2', 'segment_text': 'Giao'},
            {'document_id': 'd1', 'segment_id': 's3', 'source_location': 'page:1/block:3', 'segment_text': 'thực hiện nhiệm vụ'},
        ]
        approved = [
            {
                'annotation_unit_id': 'pilot_merge', 'document_id': 'd1',
                'unit_text': 'Giao thực hiện nhiệm vụ', 'task_present': '1',
                'commune_relevance': '1', 'label_status': 'approved_pilot',
            }
        ]
        mapping = [
            {'annotation_unit_id': 'pilot_merge', 'document_id': 'd1', 'member_order': '1', 'segment_id': 's2', 'source_location': 'page:1/block:2'},
            {'annotation_unit_id': 'pilot_merge', 'document_id': 'd1', 'member_order': '2', 'segment_id': 's3', 'source_location': 'page:1/block:3'},
        ]
        units, mappings, readiness = expansion.build_proposals(manifest, segments, approved, mapping)
        self.assertEqual(len(units), 2)
        self.assertEqual(len(mappings), 3)
        self.assertEqual(len({row['segment_id'] for row in mappings}), 3)
        pilot = next(row for row in units if row['annotation_unit_id'] == 'pilot_merge')
        self.assertEqual(pilot['proposal_status'], 'pilot_approved')
        identity = next(row for row in units if row['annotation_unit_id'] != 'pilot_merge')
        self.assertEqual(identity['eligible_for_expansion'], '1')
        self.assertEqual(readiness[0]['metadata_ready'], '1')

    def test_short_identity_is_flagged_not_automatically_merged(self):
        manifest = [
            {
                'document_id': 'd1', 'family_id': '', 'doc_date': '',
                'source_url_or_archive': '', 'permission_basis': '',
                'access_level': '', 'anonymized': '',
            }
        ]
        segments = [
            {'document_id': 'd1', 'segment_id': 's1', 'source_location': 'page:1/block:1', 'segment_text': 'giao'},
        ]
        units, mappings, readiness = expansion.build_proposals(manifest, segments, [], [])
        self.assertEqual(units[0]['proposal_status'], 'needs_segmentation_review')
        self.assertIn('short_lt20', units[0]['flags'])
        self.assertEqual(units[0]['member_count'], 1)
        self.assertEqual(units[0]['eligible_for_expansion'], '0')
        self.assertEqual(readiness[0]['metadata_ready'], '0')

    def test_family_candidates_require_multiple_informative_shared_segments(self):
        shared = [
            'Đây là đoạn nội dung đủ dài thứ nhất dùng để kiểm tra.',
            'Đây là đoạn nội dung đủ dài thứ hai dùng để kiểm tra.',
            'Đây là đoạn nội dung đủ dài thứ ba dùng để kiểm tra.',
        ]
        rows = []
        for document in ('d1', 'd2'):
            for index, text in enumerate(shared, 1):
                rows.append({'document_id': document, 'segment_id': f'{document}s{index}', 'source_location': 'page:1', 'segment_text': text})
        candidates = expansion.family_candidates(rows)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]['research_status'], 'NON_GOLD_FAMILY_SUGGESTION')


if __name__ == '__main__':
    unittest.main()
