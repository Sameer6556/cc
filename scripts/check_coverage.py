"""Check that every command id appears in exactly one shard output: no gaps, no repeats (Task 1).

  python scripts/check_coverage.py --pool data/commands_pool.jsonl --shards datasets/teacher

Also checks that each id sits in the shard its line number says it should
(line_number % SHARD_COUNT == SHARD_INDEX) and that the stored text matches the pool.
Exit status 1 if anything is wrong.
"""
import argparse
import glob
import json
import os
import re
import sys
from collections import Counter


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pool', default='data/commands_pool.jsonl')
    ap.add_argument('--shards', default='datasets/teacher')
    a = ap.parse_args()

    pool = [json.loads(line) for line in open(a.pool, encoding='utf-8') if line.strip()]
    line_of = {r['id']: n for n, r in enumerate(pool)}
    text_of = {r['id']: r['text'] for r in pool}
    files = sorted(glob.glob(os.path.join(a.shards, 'shard-*.jsonl')))
    count = len(files)
    seen, problems = Counter(), []
    for path in files:
        index = int(re.search(r'shard-(\d+)\.jsonl$', path).group(1))
        n = 0
        for line in open(path, encoding='utf-8'):
            if not line.strip():
                continue
            r = json.loads(line)
            n += 1
            seen[r['id']] += 1
            if r['id'] not in line_of:
                problems.append(f'{r["id"]} is not in the pool')
            elif line_of[r['id']] % count != index:
                ln = line_of[r['id']]
                problems.append(f'{r["id"]} (line {ln}) is in shard {index}, expected {ln % count}')
            elif r['text'] != text_of[r['id']]:
                problems.append(f'{r["id"]}: text differs from the pool')
        print(f'{os.path.basename(path)}: {n} records')
    missing = [i for i in line_of if seen[i] == 0]
    repeated = [i for i, c in seen.items() if c > 1]
    print(f'pool ids: {len(pool)}  shards: {count}  ids covered: {sum(1 for i in line_of if seen[i])}')
    print(f'missing ids (gaps): {len(missing)} {missing[:10]}')
    print(f'ids in more than one record (repeats): {len(repeated)} {repeated[:10]}')
    print(f'placement / text problems: {len(problems)} {problems[:10]}')
    ok = not missing and not repeated and not problems
    print('COVERAGE OK: every id appears in exactly one shard output' if ok else 'COVERAGE FAILED')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
