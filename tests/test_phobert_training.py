import importlib.util
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / 'scripts' / 'train_pap_ner.py'
SPEC = importlib.util.spec_from_file_location('sf2026_train_pap_ner', SCRIPT_PATH)
training = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(training)


class FakeTokenizer:
    bos_token_id = 0
    eos_token_id = 2
    cls_token_id = None
    sep_token_id = None
    unk_token_id = 3

    def encode(self, token, add_special_tokens=False):
        if token == 'hai_subtoken':
            return [10, 11]
        return [12]


class PhoBertTrainingTests(unittest.TestCase):
    def test_subtoken_alignment_uses_first_subtoken_only(self):
        label2id = {label: index for index, label in enumerate(training.LABELS)}
        example = {
            'tokens': ['Ủy_ban', 'hai_subtoken'],
            'ner_tags': ['B-CQ', 'I-CQ'],
        }
        encoded = training.encode_words(example, FakeTokenizer(), label2id, max_length=10)
        self.assertEqual(encoded['input_ids'], [0, 12, 10, 11, 2])
        self.assertEqual(encoded['labels'], [-100, label2id['B-CQ'], label2id['I-CQ'], -100, -100])
        self.assertEqual(encoded['used_words'], 2)

    def test_truncation_stops_at_word_boundary(self):
        label2id = {label: index for index, label in enumerate(training.LABELS)}
        example = {
            'tokens': ['một', 'hai_subtoken'],
            'ner_tags': ['O', 'B-CQ'],
        }
        encoded = training.encode_words(example, FakeTokenizer(), label2id, max_length=4)
        self.assertEqual(encoded['input_ids'], [0, 12, 2])
        self.assertEqual(encoded['used_words'], 1)

    def test_label_inventory_has_five_bio_entity_types(self):
        self.assertEqual(len(training.LABELS), 11)
        self.assertEqual(training.LABELS[0], 'O')
        for entity in ('CQ', 'VBPL', 'ĐT', 'NG', 'SL'):
            self.assertIn(f'B-{entity}', training.LABELS)
            self.assertIn(f'I-{entity}', training.LABELS)


if __name__ == '__main__':
    unittest.main()
