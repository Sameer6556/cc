"""Convert raw model/teacher output lines into the predictions format score.py expects.

  python scripts/to_predictions.py RAW.jsonl PREDICTIONS.jsonl [--field teacher_raw]

RAW lines look like {"id": ..., "text": ..., "<field>": "<raw reply>"}; the output lines are
{"id": ..., "prediction": "<raw reply>"} with the reply copied unchanged.
"""
import argparse
import json


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('raw')
    ap.add_argument('out')
    ap.add_argument('--field', default='teacher_raw')
    a = ap.parse_args()
    n = 0
    with open(a.raw, encoding='utf-8') as fin, open(a.out, 'w', encoding='utf-8') as fout:
        for line in fin:
            if line.strip():
                r = json.loads(line)
                fout.write(json.dumps({'id': r['id'], 'prediction': r[a.field]}, ensure_ascii=False) + '\n')
                n += 1
    print(f'wrote {n} predictions to {a.out}')


if __name__ == '__main__':
    main()
