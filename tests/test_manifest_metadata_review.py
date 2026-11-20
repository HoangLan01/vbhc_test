import importlib.util
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / 'scripts' / 'review_manifest_metadata.py'
SPEC = importlib.util.spec_from_file_location('sf2026_manifest_review', SCRIPT_PATH)
review = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(review)


class ManifestMetadataReviewTests(unittest.TestCase):
    def test_build_review_prefills_verified_date_and_family_suggestion(self):
        manifest = [{
            'document_id': 'd1', 'filename': 'data/raw/a.pdf', 'file_sha256': 'abc',
            'family_id': '', 'doc_date': '', 'doc_type': 'pdf',
            'source_url_or_archive': '', 'permission_basis': '',
            'access_level': '', 'anonymized': '',
        }]
        dates = [{
            'document_id': 'd1', 'verified_iso': '2026-01-02',
            'verification_method': 'manual', 'review_status': 'verified',
        }]
        families = [{
            'document_id_a': 'd1', 'document_id_b': 'd2',
            'containment': '0.8', 'jaccard': '0.6',
        }]
        rows = review.build_review_rows(manifest, dates, families)
        self.assertEqual(rows[0]['doc_date'], '2026-01-02')
        self.assertIn('d2', rows[0]['family_suggestions'])
        self.assertEqual(rows[0]['review_status'], '')

    def test_identity_guard_rejects_filename_or_hash_change(self):
        manifest = [{'document_id': 'd1', 'filename': 'a.pdf', 'file_sha256': 'abc'}]
        valid = [{'document_id': 'd1', 'filename': 'a.pdf', 'file_sha256': 'abc'}]
        review.validate_review_identity(manifest, valid)
        invalid = [{'document_id': 'd1', 'filename': 'b.pdf', 'file_sha256': 'abc'}]
        with self.assertRaises(ValueError):
            review.validate_review_identity(manifest, invalid)

    def test_approve_requires_all_metadata_and_valid_date(self):
        row = {'research_status': ''}
        values = {
            'family_id': 'family-1',
            'doc_date': '2026-11-19',
            'source_url_or_archive': 'archive://source',
            'permission_basis': 'Đã xác nhận quyền dùng',
            'access_level': 'public',
            'anonymized': 'no',
            'reviewer_id': 'R01',
            'review_status': '',
            'review_notes': '',
        }
        review.apply_form_values(row, values, approving=True)
        self.assertEqual(row['review_status'], 'approved')
        self.assertEqual(row['family_id'], 'family-1')
        invalid = dict(values, source_url_or_archive='')
        with self.assertRaises(ValueError):
            review.apply_form_values({}, invalid, approving=True)
        invalid_date = dict(values, doc_date='19/11/2026')
        with self.assertRaises(ValueError):
            review.apply_form_values({}, invalid_date, approving=True)

    def test_family_components_and_ids_are_stable(self):
        pairs = [
            {'document_id_a': 'd1', 'document_id_b': 'd2'},
            {'document_id_a': 'd2', 'document_id_b': 'd3'},
        ]
        components = review.family_components(pairs)
        self.assertEqual(len(components), 1)
        self.assertEqual(components[0], {'d1', 'd2', 'd3'})
        self.assertEqual(review.group_family_id({'d1', 'd2'}), review.group_family_id({'d2', 'd1'}))
        row = {'document_id': 'doc1', 'filename': 'data/raw/Văn bản 01.pdf'}
        self.assertTrue(review.unique_family_id(row).startswith('fam_van_ban_01_'))


if __name__ == '__main__':
    unittest.main()
