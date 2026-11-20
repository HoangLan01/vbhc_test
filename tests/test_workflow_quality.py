import argparse
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd


WORKFLOW_PATH = Path(__file__).resolve().parents[1] / 'scripts' / 'workflow.py'
SPEC = importlib.util.spec_from_file_location('sf2026_workflow', WORKFLOW_PATH)
workflow = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(workflow)


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PilotSelectionTests(unittest.TestCase):
    def make_segments(self):
        rows = []
        for document_number in range(1, 5):
            document_id = f'doc_{document_number}'
            for segment_number in range(1, 11):
                if segment_number % 2:
                    text = f'Giao thực hiện nhiệm vụ số {segment_number} của tài liệu {document_number}.'
                else:
                    text = f'Thông tin tham khảo số {segment_number} của tài liệu {document_number}.'
                if segment_number == 10:
                    text += ' | cột bảng'
                rows.append(dict(
                    document_id=document_id,
                    segment_id=f'{document_id}_S{segment_number:04d}',
                    source_location=f'page:1/block:{segment_number}',
                    segment_text=text,
                ))
        return pd.DataFrame(rows)

    def test_selection_is_deterministic_and_covers_documents(self):
        segments = self.make_segments()
        first = workflow.select_pilot_rows(segments, n=16, seed=42, min_per_document=3)
        second = workflow.select_pilot_rows(segments, n=16, seed=42, min_per_document=3)
        self.assertEqual(first.segment_id.tolist(), second.segment_id.tolist())
        self.assertEqual(len(first), 16)
        self.assertEqual(first.segment_id.nunique(), 16)
        self.assertTrue((first.groupby('document_id').size() >= 3).all())
        self.assertEqual(set(first.document_id), set(segments.document_id))

    def test_annotation_forms_have_blank_labels_and_no_heuristic_columns(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            old_root = workflow.ROOT
            workflow.ROOT = Path(temp_dir)
            try:
                workflow.dump_csv(
                    'data/processed/candidate_segments.csv',
                    self.make_segments().to_dict('records'),
                    workflow.DRAFT,
                )
                args = argparse.Namespace(
                    n=16,
                    seed=7,
                    min_per_document=3,
                    master='data/annotations/pilot_segments.csv',
                    annotator_a='data/annotations/segments_annotatorA.csv',
                    annotator_b='data/annotations/segments_annotatorB.csv',
                    summary='results/quality/pilot_selection_summary.csv',
                    force=False,
                )
                workflow.sample_pilot(args)
                form_a = workflow.read_csv(args.annotator_a)
                form_b = workflow.read_csv(args.annotator_b)
                self.assertEqual(form_a.segment_id.tolist(), form_b.segment_id.tolist())
                self.assertEqual(form_a.columns.tolist(), workflow.SEGMENTS)
                self.assertNotIn('heuristic_task_signal', form_a.columns)
                for column in ['task_present', 'commune_relevance', 'annotator_id', 'label_status', 'notes']:
                    self.assertTrue(form_a[column].eq('').all())
            finally:
                workflow.ROOT = old_root

    def test_ai_suggestions_are_separate_non_gold_and_do_not_change_forms(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            old_root = workflow.ROOT
            workflow.ROOT = Path(temp_dir)
            try:
                workflow.dump_csv(
                    'data/processed/candidate_segments.csv',
                    self.make_segments().to_dict('records'),
                    workflow.DRAFT,
                )
                workflow.sample_pilot(argparse.Namespace(
                    n=16,
                    seed=7,
                    min_per_document=3,
                    master='data/annotations/pilot_segments.csv',
                    annotator_a='data/annotations/segments_annotatorA.csv',
                    annotator_b='data/annotations/segments_annotatorB.csv',
                    summary='results/quality/pilot_selection_summary.csv',
                    force=False,
                ))
                form_paths = [
                    workflow.project('data/annotations/segments_annotatorA.csv'),
                    workflow.project('data/annotations/segments_annotatorB.csv'),
                ]
                before = [file_hash(path) for path in form_paths]
                args = argparse.Namespace(
                    input='data/annotations/pilot_segments.csv',
                    output='data/annotations/segments_ai_suggestions.csv',
                    force=False,
                )
                workflow.suggest_pilot_labels(args)
                after = [file_hash(path) for path in form_paths]
                suggestions = workflow.read_csv(args.output)
                self.assertEqual(before, after)
                self.assertEqual(len(suggestions), 16)
                self.assertTrue(suggestions.research_status.eq('NON_GOLD_AI_SUGGESTION').all())
                self.assertTrue(suggestions.human_review_required.eq('1').all())
                self.assertTrue(suggestions.suggestion_method.eq('local_rule_keywords_v1').all())
                self.assertNotIn('task_present', suggestions.columns)
                with self.assertRaises(SystemExit):
                    workflow.suggest_pilot_labels(args)
            finally:
                workflow.ROOT = old_root


class QualityReportTests(unittest.TestCase):
    def test_quality_report_is_derived_and_does_not_change_inputs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            old_root = workflow.ROOT
            workflow.ROOT = Path(temp_dir)
            try:
                raw = workflow.project('data/raw/doc.txt')
                raw.parent.mkdir(parents=True, exist_ok=True)
                raw.write_text('Dữ liệu giả phục vụ kiểm thử.', encoding='utf-8')
                manifest_row = dict(
                    document_id='doc_1',
                    filename='data/raw/doc.txt',
                    file_sha256=workflow.sha256(raw),
                    family_id='',
                    doc_date='',
                    doc_type='txt',
                    source_url_or_archive='',
                    permission_basis='',
                    access_level='',
                    anonymized='',
                    notes='FIXTURE GIẢ',
                )
                segment_rows = [
                    dict(document_id='doc_1', segment_id='doc_1_S0001', source_location='line:1', segment_text='Ngắn'),
                    dict(document_id='doc_1', segment_id='doc_1_S0002', source_location='line:2', segment_text='Ngắn'),
                ]
                workflow.dump_csv('data/processed/documents_manifest.csv', [manifest_row], workflow.MANIFEST)
                workflow.dump_csv('data/processed/candidate_segments.csv', segment_rows, workflow.DRAFT)
                manifest_path = workflow.project('data/processed/documents_manifest.csv')
                segments_path = workflow.project('data/processed/candidate_segments.csv')
                before = (file_hash(manifest_path), file_hash(segments_path))
                workflow.quality_report(argparse.Namespace(output_dir='results/quality', force=False))
                after = (file_hash(manifest_path), file_hash(segments_path))
                self.assertEqual(before, after)
                summary = workflow.read_csv('results/quality/dataset_quality_summary.csv')
                values = summary.set_index('metric').value.to_dict()
                self.assertEqual(values['candidate_segments'], '2')
                self.assertEqual(values['duplicate_text_groups'], '1')
                self.assertEqual(values['raw_status_ok'], '1')
            finally:
                workflow.ROOT = old_root


class IncrementalIngestTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_root = workflow.ROOT
        workflow.ROOT = Path(self.temp_dir.name)
        raw = workflow.project('data/raw')
        raw.mkdir(parents=True, exist_ok=True)
        self.old_file = raw / 'old.txt'
        self.old_file.write_text('Đoạn cũ đã được nhập.\n', encoding='utf-8')
        self.old_document_id = 'old_document_fixed'
        self.old_manifest = dict(
            document_id=self.old_document_id,
            filename='data/raw/old.txt',
            file_sha256=workflow.sha256(self.old_file),
            family_id='family_preserved',
            doc_date='2026-01-02',
            doc_type='cong_van',
            source_url_or_archive='public_fixture_archive',
            permission_basis='FIXTURE GIẢ - KHÔNG PHẢI DỮ LIỆU NGHIÊN CỨU',
            access_level='public',
            anonymized='yes',
            notes='METADATA PHẢI GIỮ NGUYÊN',
        )
        self.old_segment = dict(
            document_id=self.old_document_id,
            segment_id=f'{self.old_document_id}_S0001',
            source_location='line:1',
            segment_text='Đoạn cũ đã được nhập.',
        )
        old_gold = dict(
            **self.old_segment,
            task_present='1',
            commune_relevance='1',
            annotator_id='fixture_annotator',
            label_status='approved',
            notes='NHÃN CŨ PHẢI GIỮ NGUYÊN',
        )
        workflow.dump_csv('data/processed/documents_manifest.csv', [self.old_manifest], workflow.MANIFEST)
        workflow.dump_csv('data/processed/candidate_segments.csv', [self.old_segment], workflow.DRAFT)
        workflow.dump_csv('data/annotations/segments_gold.csv', [old_gold], workflow.SEGMENTS)

    def tearDown(self):
        workflow.ROOT = self.old_root
        self.temp_dir.cleanup()

    def args(self, ocr=False, force=False):
        return argparse.Namespace(incremental=True, ocr=ocr, force=force)

    def latest_log(self):
        logs = sorted(workflow.project('evidence').glob('ingest_incremental_*.json'))
        self.assertTrue(logs)
        return json.loads(logs[-1].read_text(encoding='utf-8'))

    def test_incremental_is_idempotent_and_preserves_metadata_and_labels(self):
        new_file = workflow.project('data/raw/new.txt')
        new_file.write_text('Đoạn mới thứ nhất.\nĐoạn mới thứ hai.\n', encoding='utf-8')
        renamed_duplicate = workflow.project('data/raw/renamed_old.txt')
        renamed_duplicate.write_bytes(self.old_file.read_bytes())

        workflow.ingest(self.args())
        manifest_after_first = workflow.read_csv('data/processed/documents_manifest.csv')
        segments_after_first = workflow.read_csv('data/processed/candidate_segments.csv')
        gold_after_first = workflow.read_csv('data/annotations/segments_gold.csv')
        self.assertEqual(len(manifest_after_first), 2)
        self.assertEqual(len(segments_after_first), 3)
        self.assertEqual(len(gold_after_first), 3)
        self.assertFalse(manifest_after_first.document_id.duplicated().any())
        self.assertFalse(segments_after_first.segment_id.duplicated().any())
        preserved = manifest_after_first[manifest_after_first.document_id.eq(self.old_document_id)].iloc[0]
        for key, value in self.old_manifest.items():
            self.assertEqual(preserved[key], value)
        preserved_gold = gold_after_first[gold_after_first.segment_id.eq(self.old_segment['segment_id'])].iloc[0]
        self.assertEqual(preserved_gold.task_present, '1')
        self.assertEqual(preserved_gold.label_status, 'approved')
        self.assertEqual(preserved_gold.notes, 'NHÃN CŨ PHẢI GIỮ NGUYÊN')
        new_gold = gold_after_first[~gold_after_first.segment_id.eq(self.old_segment['segment_id'])]
        self.assertTrue(new_gold.task_present.eq('').all())
        self.assertTrue(new_gold.label_status.eq('').all())
        first_log = self.latest_log()
        self.assertEqual(first_log['new_document_count'], 1)
        self.assertEqual(first_log['segments_appended'], 2)
        self.assertEqual(first_log['annotations_appended'], 2)
        self.assertEqual(first_log['skipped_duplicate_count'], 2)

        workflow.ingest(self.args())
        manifest_after_second = workflow.read_csv('data/processed/documents_manifest.csv')
        segments_after_second = workflow.read_csv('data/processed/candidate_segments.csv')
        gold_after_second = workflow.read_csv('data/annotations/segments_gold.csv')
        self.assertEqual(len(manifest_after_second), 2)
        self.assertEqual(len(segments_after_second), 3)
        self.assertEqual(len(gold_after_second), 3)
        self.assertFalse(manifest_after_second.document_id.duplicated().any())
        self.assertFalse(segments_after_second.segment_id.duplicated().any())
        self.assertFalse(gold_after_second.segment_id.duplicated().any())
        second_log = self.latest_log()
        self.assertEqual(second_log['new_document_count'], 0)
        self.assertEqual(second_log['segments_appended'], 0)
        self.assertEqual(second_log['skipped_duplicate_count'], 3)

    def test_modified_existing_file_is_warned_and_not_overwritten(self):
        manifest_hash_before = file_hash(workflow.project('data/processed/documents_manifest.csv'))
        segments_hash_before = file_hash(workflow.project('data/processed/candidate_segments.csv'))
        self.old_file.write_text('Nội dung cũ đã bị thay đổi và cần xử lý riêng.\n', encoding='utf-8')

        workflow.ingest(self.args())

        self.assertEqual(file_hash(workflow.project('data/processed/documents_manifest.csv')), manifest_hash_before)
        self.assertEqual(file_hash(workflow.project('data/processed/candidate_segments.csv')), segments_hash_before)
        log = self.latest_log()
        self.assertEqual(log['modified_document_count'], 1)
        self.assertEqual(log['new_document_count'], 0)
        self.assertFalse(log['committed'])

    def test_ocr_flag_is_forwarded_for_new_documents(self):
        scan = workflow.project('data/raw/scan.pdf')
        scan.write_bytes(b'%PDF-FAKE-FIXTURE')
        with mock.patch.object(
            workflow,
            'segments_of_file',
            return_value=[('page:1/OCR', 'Nội dung OCR giả để kiểm thử.')],
        ) as extractor:
            workflow.ingest(self.args(ocr=True))
        calls = [call for call in extractor.call_args_list if call.args[0].name == 'scan.pdf']
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0].args[1])
        manifest = workflow.read_csv('data/processed/documents_manifest.csv')
        self.assertEqual(len(manifest), 2)

    def test_empty_gold_template_remains_empty(self):
        workflow.dump_csv('data/annotations/segments_gold.csv', [], workflow.SEGMENTS)
        workflow.project('data/raw/new.txt').write_text('Đoạn mới chưa được gán nhãn.\n', encoding='utf-8')

        workflow.ingest(self.args())

        gold = workflow.read_csv('data/annotations/segments_gold.csv')
        candidates = workflow.read_csv('data/processed/candidate_segments.csv')
        self.assertTrue(gold.empty)
        self.assertEqual(len(candidates), 2)
        self.assertEqual(self.latest_log()['annotations_appended'], 0)

    def test_incremental_rejects_force(self):
        with self.assertRaises(SystemExit):
            workflow.ingest(self.args(force=True))


if __name__ == '__main__':
    unittest.main()
