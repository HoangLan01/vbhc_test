import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / 'scripts' / 'review_routing.py'
SPEC = importlib.util.spec_from_file_location('sf2026_routing_review', SCRIPT_PATH)
review = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(review)


class RoutingReviewTests(unittest.TestCase):
    def setUp(self):
        self.units = {'u1', 'u2'}
        self.prediction = {
            'task_id': 't1',
            'document_id': 'd1',
            'method': 'phobert_hybrid',
            'candidate1': 'u1',
            'candidate2': 'u2',
            'score1': '0.8',
            'score2': '0.6',
            'abstain': '0',
            'model': 'vinai/phobert-base',
            'alpha': '',
            'threshold': '0.5',
            'margin': '0.1',
        }

    def build_row(self):
        return review.build_review_rows([self.prediction], 'a' * 64, 'b' * 64, {'t1'}, self.units)[0]

    def test_prepare_marks_review_as_non_gold(self):
        row = self.build_row()
        self.assertEqual(row['review_decision'], '')
        self.assertEqual(row['research_status'], 'HUMAN_ROUTING_REVIEW_NOT_ADJUDICATED_GOLD')
        self.assertEqual(row['source_prediction_sha256'], 'a' * 64)

    def test_accept_uses_candidate1_and_requires_evidence(self):
        row = self.build_row()
        with self.assertRaises(ValueError):
            review.apply_review(row, 'accept', '', 'R01', '', '', self.units)
        review.apply_review(row, 'accept', '', 'R01', 'Phù hợp chức năng', 'Văn bản chức năng số X', self.units)
        self.assertEqual(row['final_unit'], 'u1')
        self.assertEqual(row['review_status'], 'draft_human_review')

    def test_reroute_and_abstain_contracts(self):
        row = self.build_row()
        review.apply_review(row, 'reroute', 'u2', 'R01', 'Chọn lại', 'Căn cứ Y', self.units)
        self.assertEqual(row['final_unit'], 'u2')
        with self.assertRaises(ValueError):
            review.apply_review(row, 'abstain', 'u1', 'R01', '', '', self.units)

    def test_unknown_task_or_unit_is_rejected(self):
        with self.assertRaises(ValueError):
            review.build_review_rows([self.prediction], 'a', 'b', {'other'}, self.units)
        bad = dict(self.prediction, candidate1='unknown')
        with self.assertRaises(ValueError):
            review.build_review_rows([bad], 'a', 'b', {'t1'}, self.units)

    def test_audit_rejects_sensitive_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'audit.jsonl'
            review.append_audit_event(path, {'event_type': 'routing_review.recorded', 'task_id': 't1'})
            payload = json.loads(path.read_text(encoding='utf-8').strip())
            self.assertEqual(payload['task_id'], 't1')
            with self.assertRaises(ValueError):
                review.append_audit_event(path, {'evidence_unit': 'Không ghi vào audit'})


if __name__ == '__main__':
    unittest.main()
