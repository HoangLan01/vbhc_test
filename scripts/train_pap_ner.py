#!/usr/bin/env python3
"""Fine-tune PhoBERT token classification trên PAP_NER external corpus.

Kết quả chỉ là external-transfer benchmark, không phải E1-E5 target result.
"""

import argparse
import inspect
import json
import os
import platform
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = ROOT / 'data' / 'external' / 'pap_ner' / 'prepared'
DEFAULT_OUTPUT = ROOT / 'results' / 'external' / 'pap_ner'
DEFAULT_CACHE = ROOT / 'models' / 'cache' / 'huggingface'
LABELS = [
    'O',
    'B-CQ', 'I-CQ',
    'B-VBPL', 'I-VBPL',
    'B-ĐT', 'I-ĐT',
    'B-NG', 'I-NG',
    'B-SL', 'I-SL',
]


def configure_utf8_console():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')


def set_seed_everywhere(seed):
    random.seed(seed)
    np.random.seed(seed)
    import torch

    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def encode_words(example, tokenizer, label2id, max_length):
    bos = tokenizer.bos_token_id if tokenizer.bos_token_id is not None else tokenizer.cls_token_id
    eos = tokenizer.eos_token_id if tokenizer.eos_token_id is not None else tokenizer.sep_token_id
    if bos is None or eos is None:
        raise ValueError('Tokenizer không có BOS/EOS hoặc CLS/SEP token.')
    input_ids = [bos]
    labels = [-100]
    used_words = 0
    for token, label in zip(example['tokens'], example['ner_tags']):
        subtoken_ids = tokenizer.encode(token, add_special_tokens=False)
        if not subtoken_ids:
            subtoken_ids = [tokenizer.unk_token_id]
        if len(input_ids) + len(subtoken_ids) + 1 > max_length:
            break
        input_ids.extend(subtoken_ids)
        labels.append(label2id[label])
        labels.extend([-100] * (len(subtoken_ids) - 1))
        used_words += 1
    input_ids.append(eos)
    labels.append(-100)
    return {
        'input_ids': input_ids,
        'attention_mask': [1] * len(input_ids),
        'labels': labels,
        'used_words': used_words,
    }


def build_compute_metrics(id2label):
    from seqeval.metrics import accuracy_score, f1_score, precision_score, recall_score

    def compute_metrics(eval_prediction):
        logits, label_ids = eval_prediction
        predictions = np.argmax(logits, axis=-1)
        true_predictions = []
        true_labels = []
        for prediction_row, label_row in zip(predictions, label_ids):
            predicted_tags = []
            gold_tags = []
            for predicted, gold in zip(prediction_row, label_row):
                if gold == -100:
                    continue
                predicted_tags.append(id2label[int(predicted)])
                gold_tags.append(id2label[int(gold)])
            true_predictions.append(predicted_tags)
            true_labels.append(gold_tags)
        return {
            'precision': precision_score(true_labels, true_predictions, zero_division=0),
            'recall': recall_score(true_labels, true_predictions, zero_division=0),
            'f1': f1_score(true_labels, true_predictions, zero_division=0),
            'accuracy': accuracy_score(true_labels, true_predictions),
        }

    return compute_metrics


def json_dump_atomic(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f'.{path.name}.{os.getpid()}.tmp')
    try:
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def write_predictions(path, sentence_ids, logits, label_ids, id2label):
    predictions = np.argmax(logits, axis=-1)
    temp = path.with_name(f'.{path.name}.{os.getpid()}.tmp')
    try:
        with temp.open('w', encoding='utf-8', newline='\n') as stream:
            for sentence_id, prediction_row, label_row in zip(sentence_ids, predictions, label_ids):
                predicted_tags = []
                gold_tags = []
                for predicted, gold in zip(prediction_row, label_row):
                    if gold == -100:
                        continue
                    predicted_tags.append(id2label[int(predicted)])
                    gold_tags.append(id2label[int(gold)])
                stream.write(json.dumps({
                    'sentence_id': sentence_id,
                    'predicted_tags': predicted_tags,
                    'gold_tags': gold_tags,
                    'research_status': 'EXTERNAL_PAP_NER_PREDICTION',
                }, ensure_ascii=False, separators=(',', ':')) + '\n')
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def load_splits(data_dir, smoke):
    from datasets import load_dataset

    data_files = {
        'train': str(data_dir / 'train.jsonl'),
        'validation': str(data_dir / 'dev.jsonl'),
        'test': str(data_dir / 'test.jsonl'),
    }
    dataset = load_dataset('json', data_files=data_files)
    if smoke:
        limits = {'train': 128, 'validation': 32, 'test': 32}
        for split, limit in limits.items():
            dataset[split] = dataset[split].select(range(min(limit, len(dataset[split]))))
    return dataset


def main():
    configure_utf8_console()
    parser = argparse.ArgumentParser(description='Fine-tune PhoBERT trên PAP_NER external corpus.')
    parser.add_argument('--data-dir', default=str(DEFAULT_DATA))
    parser.add_argument('--output-dir', default=str(DEFAULT_OUTPUT))
    parser.add_argument('--model-name', default='vinai/phobert-base')
    parser.add_argument('--cache-dir', default=str(DEFAULT_CACHE))
    parser.add_argument('--max-length', type=int, default=256)
    parser.add_argument('--train-batch-size', type=int, default=8)
    parser.add_argument('--eval-batch-size', type=int, default=8)
    parser.add_argument('--gradient-accumulation-steps', type=int, default=2)
    parser.add_argument('--learning-rate', type=float, default=2e-5)
    parser.add_argument('--epochs', type=float, default=3.0)
    parser.add_argument('--weight-decay', type=float, default=0.01)
    parser.add_argument('--warmup-ratio', type=float, default=0.1)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--smoke', action='store_true', help='Chạy 128/32/32 mẫu, 1 epoch, tối đa 2 step.')
    parser.add_argument('--allow-cpu-full', action='store_true')
    args = parser.parse_args()

    try:
        import torch
        import transformers
        from transformers import (
            AutoModelForTokenClassification,
            AutoTokenizer,
            DataCollatorForTokenClassification,
            Trainer,
            TrainingArguments,
        )
    except ImportError as exc:
        raise SystemExit('Thiếu thư viện ML. Cài requirements-ml.txt trước.') from exc

    data_dir = Path(args.data_dir)
    for filename in ('train.jsonl', 'dev.jsonl', 'test.jsonl'):
        if not (data_dir / filename).is_file():
            raise SystemExit(f'Chưa có file: {data_dir / filename}')
    if not torch.cuda.is_available() and not args.smoke and not args.allow_cpu_full:
        raise SystemExit('Không có CUDA. Chỉ chạy --smoke hoặc dùng --allow-cpu-full sau khi cân nhắc thời gian.')

    set_seed_everywhere(args.seed)
    run_kind = 'smoke_non_research' if args.smoke else 'full_external_benchmark'
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    run_dir = Path(args.output_dir) / f'{run_kind}_seed{args.seed}_{stamp}'
    if run_dir.exists():
        raise SystemExit(f'Output đã tồn tại: {run_dir}')
    run_dir.mkdir(parents=True)
    cache_dir = Path(args.cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    label2id = {label: index for index, label in enumerate(LABELS)}
    id2label = {index: label for label, index in label2id.items()}
    tokenizer = AutoTokenizer.from_pretrained(args.model_name, cache_dir=cache_dir, use_fast=False)
    model = AutoModelForTokenClassification.from_pretrained(
        args.model_name,
        cache_dir=cache_dir,
        num_labels=len(LABELS),
        id2label=id2label,
        label2id=label2id,
    )
    dataset = load_splits(data_dir, args.smoke)
    sentence_ids = {split: dataset[split]['sentence_id'] for split in dataset}

    def encode(example):
        return encode_words(example, tokenizer, label2id, args.max_length)

    tokenized = dataset.map(
        encode,
        remove_columns=dataset['train'].column_names,
        desc='Tokenize và căn chỉnh BIO',
    )
    epochs = 1.0 if args.smoke else args.epochs
    training_kwargs = dict(
        output_dir=str(run_dir / 'checkpoints'),
        learning_rate=args.learning_rate,
        per_device_train_batch_size=args.train_batch_size,
        per_device_eval_batch_size=args.eval_batch_size,
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        num_train_epochs=epochs,
        weight_decay=args.weight_decay,
        warmup_ratio=args.warmup_ratio,
        save_strategy='epoch',
        load_best_model_at_end=True,
        metric_for_best_model='f1',
        greater_is_better=True,
        save_total_limit=2,
        seed=args.seed,
        data_seed=args.seed,
        report_to=[],
        fp16=bool(torch.cuda.is_available()),
        dataloader_num_workers=0,
        remove_unused_columns=True,
        logging_steps=1 if args.smoke else 100,
    )
    parameters = inspect.signature(TrainingArguments.__init__).parameters
    if 'eval_strategy' in parameters:
        training_kwargs['eval_strategy'] = 'epoch'
    else:
        training_kwargs['evaluation_strategy'] = 'epoch'
    if args.smoke:
        training_kwargs['max_steps'] = 2
        training_kwargs['save_strategy'] = 'steps'
        training_kwargs['eval_strategy' if 'eval_strategy' in parameters else 'evaluation_strategy'] = 'steps'
        training_kwargs['eval_steps'] = 1
        training_kwargs['save_steps'] = 1

    training_args = TrainingArguments(**training_kwargs)
    trainer_kwargs = dict(
        model=model,
        args=training_args,
        train_dataset=tokenized['train'],
        eval_dataset=tokenized['validation'],
        data_collator=DataCollatorForTokenClassification(tokenizer),
        compute_metrics=build_compute_metrics(id2label),
    )
    trainer_parameters = inspect.signature(Trainer.__init__).parameters
    if 'processing_class' in trainer_parameters:
        trainer_kwargs['processing_class'] = tokenizer
    else:
        trainer_kwargs['tokenizer'] = tokenizer
    trainer = Trainer(**trainer_kwargs)
    train_result = trainer.train()
    trainer.save_model(run_dir / 'model')
    tokenizer.save_pretrained(run_dir / 'model')
    prediction = trainer.predict(tokenized['test'])
    metrics = {key: float(value) for key, value in prediction.metrics.items()}
    json_dump_atomic(run_dir / 'metrics_test.json', metrics)
    write_predictions(
        run_dir / 'predictions_test.jsonl',
        sentence_ids['test'],
        prediction.predictions,
        prediction.label_ids,
        id2label,
    )

    prepared_manifest = ROOT / 'data' / 'external' / 'prepared_manifest.json'
    payload = {
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'research_status': 'SMOKE_NON_RESEARCH' if args.smoke else 'EXTERNAL_BENCHMARK_NOT_TARGET_E1_E5',
        'model_name': args.model_name,
        'model_revision': getattr(model.config, '_commit_hash', None),
        'labels': LABELS,
        'config': vars(args),
        'device': str(training_args.device),
        'torch_version': torch.__version__,
        'transformers_version': transformers.__version__,
        'python': sys.version,
        'platform': platform.platform(),
        'train_metrics': {key: float(value) for key, value in train_result.metrics.items()},
        'test_metrics': metrics,
        'prepared_manifest': json.loads(prepared_manifest.read_text(encoding='utf-8')) if prepared_manifest.exists() else None,
    }
    json_dump_atomic(run_dir / 'run_manifest.json', payload)
    print(f'Hoàn thành {run_kind}: {run_dir}')
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
