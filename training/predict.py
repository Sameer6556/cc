"""Run a model over a commands file and write predictions in the format score.py expects.

  python training/predict.py --model artifacts/models/v1 --out results/student_v1_validation_predictions.jsonl
  python training/predict.py --model EleutherAI/pythia-70m --out results/untrained_validation_predictions.jsonl

Uses exactly the prompt and greedy decoding of the web service (service/parser_core.py), with
max_new_tokens equal to the service's MAX_NEW_TOKENS default. Each output line is
{"id": ..., "prediction": "<raw model output>", "text": ..., "seconds": ...}.
"""
import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'service'))

from parser_core import Parser  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--model', required=True, help='local model directory or Hugging Face model id')
    ap.add_argument('--revision', default=None)
    ap.add_argument('--input', default=os.path.join(ROOT, 'data', 'validation.jsonl'))
    ap.add_argument('--out', required=True)
    ap.add_argument('--max-new-tokens', type=int, default=64)
    ap.add_argument('--threads', type=int, default=None)
    a = ap.parse_args()

    parser = Parser(a.model, revision=a.revision, num_threads=a.threads)
    rows = [json.loads(line) for line in open(a.input, encoding='utf-8') if line.strip()]
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    t_all = time.time()
    with open(a.out, 'w', encoding='utf-8') as f:
        for r in rows:
            t0 = time.time()
            pred = parser.generate(r['text'], a.max_new_tokens)
            f.write(json.dumps({'id': r['id'], 'prediction': pred, 'text': r['text'],
                                'seconds': round(time.time() - t0, 4)}, ensure_ascii=False) + '\n')
    print(f'{len(rows)} predictions in {time.time() - t_all:.1f}s -> {a.out}')


if __name__ == '__main__':
    main()
