import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / 'scripts' / 'external_datasets.py'
SPEC = importlib.util.spec_from_file_location('sf2026_external_datasets', SCRIPT_PATH)
external = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(external)


class ExternalDatasetTests(unittest.TestCase):
    def test_safe_zip_extraction(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / 'safe.zip'
            with zipfile.ZipFile(archive, 'w') as output:
                output.writestr('pdfs/doc1.pdf', b'%PDF-fixture')
                output.writestr('annotations/doc1.json', b'{"organization": [], "task": "fixture"}')
            destination = root / 'extracted'
            external.safe_extract_zip(archive, destination)
            self.assertTrue((destination / 'pdfs' / 'doc1.pdf').is_file())
            self.assertTrue((destination / 'annotations' / 'doc1.json').is_file())

    def test_zip_path_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / 'unsafe.zip'
            with zipfile.ZipFile(archive, 'w') as output:
                output.writestr('../outside.txt', b'unsafe')
            with self.assertRaises(ValueError):
                external.safe_extract_zip(archive, root / 'extracted')
            self.assertFalse((root / 'outside.txt').exists())

    def test_parse_pap_conll(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'train_data.txt'
            path.write_text(
                'Ủy_ban\tN\tB-NP\tB-CQ\tO\n'
                'nhân_dân\tN\tI-NP\tI-CQ\tO\n'
                '\n'
                'ngày\tN\tB-NP\tB-NG\tO\n'
                '20/10/2026\tM\tI-NP\tI-NG\tO\n',
                encoding='utf-8',
            )
            result = external.parse_pap_file(path)
            self.assertEqual(result['sentences'], 2)
            self.assertEqual(result['tokens'], 4)
            self.assertEqual(result['malformed_lines'], 0)
            self.assertEqual(result['column_counts'], {5: 4})
            self.assertEqual(result['entity_counts'], {'CQ': 1, 'NG': 1})
            self.assertEqual(result['auxiliary_label_counts'], {'O': 4})

    def test_resolve_url_uses_pinned_revision(self):
        url = external.resolve_url('owner/repo', 'abc123', 'folder/file name.txt')
        self.assertIn('/resolve/abc123/', url)
        self.assertIn('file%20name.txt', url)

    def test_prepare_ota_and_pap_keep_external_status(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            old_root = external.ROOT
            external.ROOT = root
            try:
                ota = root / 'data' / 'external' / 'ota'
                (ota / 'extracted' / 'pdf').mkdir(parents=True)
                (ota / 'extracted' / 'groundtruth').mkdir(parents=True)
                (ota / 'extracted' / 'pdf' / '1.pdf').write_bytes(b'%PDF-fixture')
                (ota / 'extracted' / 'groundtruth' / '1.json').write_text(
                    json.dumps([{'organization': ['Cơ quan A'], 'task': 'Thực hiện nhiệm vụ.'}], ensure_ascii=False),
                    encoding='utf-8',
                )
                ota_result = external.prepare_ota(ota, 'ota_revision')
                self.assertEqual(ota_result['documents'], 1)
                self.assertEqual(ota_result['pairs'], 1)
                pair = json.loads((ota / 'prepared' / 'ota_pairs.jsonl').read_text(encoding='utf-8').strip())
                self.assertEqual(pair['research_status'], 'EXTERNAL_OTA_NOT_TARGET_GOLD')

                pap = root / 'data' / 'external' / 'pap_ner'
                (pap / 'raw').mkdir(parents=True)
                sample = 'Ủy_ban\tN\tB-NP\tB-CQ\tO\nnhân_dân\tN\tI-NP\tI-CQ\tO\n'
                for name in ('train_data.txt', 'dev_data.txt', 'test_data.txt'):
                    (pap / 'raw' / name).write_text(sample, encoding='utf-8')
                pap_result = external.prepare_pap(pap, 'pap_revision')
                self.assertEqual(pap_result['train']['sentences'], 1)
                sentence = json.loads((pap / 'prepared' / 'train.jsonl').read_text(encoding='utf-8').strip())
                self.assertEqual(sentence['ner_tags'], ['B-CQ', 'I-CQ'])
                self.assertEqual(sentence['research_status'], 'EXTERNAL_PAP_NER_NOT_TARGET_GOLD')
            finally:
                external.ROOT = old_root


if __name__ == '__main__':
    unittest.main()
