import importlib.util
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / 'scripts' / 'sample_gold_units.py'
SPEC = importlib.util.spec_from_file_location('sf2026_sample_gold_units', SCRIPT_PATH)
sampling = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sampling)


def unit(document, index, text):
    return {
        'annotation_unit_id': f'{document}_u{index}',
        'document_id': document,
        'source_locations': f'page:1/block:{index}',
        'member_segment_ids': f'{document}_s{index}',
        'unit_text': text,
        'eligible_for_expansion': '1',
    }


class SampleGoldUnitsTests(unittest.TestCase):
    def setUp(self):
        rows = []
        for document in ('d1', 'd2', 'd3'):
            rows.extend([
                unit(document, 1, 'Ủy ban yêu cầu thực hiện báo cáo nhiệm vụ.'),
                unit(document, 2, 'Thông tin nền không có hành động bắt buộc.'),
                unit(document, 3, 'UBND xã triển khai kế hoạch.'),
                unit(document, 4, 'Đoạn mô tả dài khác để lấy mẫu.'),
            ])
        self.rows = sampling.add_features(rows)

    def test_sampling_is_deterministic_and_covers_documents(self):
        first = sampling.sample_units(self.rows, n=9, seed=43, min_per_document=3)
        second = sampling.sample_units(self.rows, n=9, seed=43, min_per_document=3)
        self.assertEqual([row['annotation_unit_id'] for row in first], [row['annotation_unit_id'] for row in second])
        counts = {}
        for row in first:
            counts[row['document_id']] = counts.get(row['document_id'], 0) + 1
        self.assertEqual(counts, {'d1': 3, 'd2': 3, 'd3': 3})

    def test_adaptive_minimum_allows_document_with_two_units(self):
        rows = self.rows + sampling.add_features([
            unit('d4', 1, 'Yêu cầu thực hiện nhiệm vụ.'),
            unit('d4', 2, 'Thông tin không nhiệm vụ.'),
        ])
        selected = sampling.sample_units(rows, n=11, seed=43, min_per_document=3)
        self.assertEqual(sum(row['document_id'] == 'd4' for row in selected), 2)

    def test_annotator_forms_are_blank_and_hide_heuristics(self):
        selected = sampling.sample_units(self.rows, n=9, seed=43, min_per_document=3)
        master, forms = sampling.build_outputs(selected)
        self.assertIn('heuristic_task_signal', master[0])
        self.assertNotIn('heuristic_task_signal', forms[0])
        self.assertEqual(forms[0]['task_present'], '')
        self.assertEqual(forms[0]['commune_relevance'], '')


if __name__ == '__main__':
    unittest.main()
