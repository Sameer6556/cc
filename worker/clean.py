"""Clean the teacher's shard outputs into the training set (Task 1, step 6).

Usage
  python worker/clean.py --shards s3://datasets/teacher/ --out s3://datasets/v1/     (in the cluster)
  python worker/clean.py --shards datasets/teacher --out datasets/v1                 (on a laptop)

Reads every shard-*.jsonl under --shards, orders all records by id and removes, in this order
(each record is counted under the FIRST reason that applies):
  (a) invalid_json      the reply (after trimming surrounding whitespace) is not valid JSON
  (b) bad_keys          the reply is not an object whose keys are exactly intent, date, time, place
                        (a key repeated inside the object also counts as (b))
  (c) bad_intent        the intent is not one of the eight intents in schema.json
  (d) slot_not_in_text  a date/time/place value is neither null nor text that appears in the command
                        (case-insensitive, compared word by word, so "mon" does not match "monday";
                        an empty string is not text that appears in the command)
  (e) duplicate         the same command (case and repeated spaces ignored) was already kept;
                        records are visited in id order, so the one with the smallest id is kept

Writes <out>/train.jsonl (records in id order) and <out>/train.sha256 (sha256sum format).
Each kept line is {"id", "text", "teacher_raw", "target"}: teacher_raw is the reply exactly as
generated and target is the same JSON object re-serialised with the key order intent, date,
time, place (values are never changed). The output is byte-for-byte deterministic.
"""
import argparse
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import s3io  # noqa: E402

KEYS = ('intent', 'date', 'time', 'place')
SLOTS = ('date', 'time', 'place')
REASONS = ('invalid_json', 'bad_keys', 'bad_intent', 'slot_not_in_text', 'duplicate')
DEFAULT_INTENTS = ('alarm_set', 'alarm_query', 'calendar_set', 'calendar_query', 'calendar_remove',
                   'weather_query', 'datetime_query', 'recommendation_events')


class _DuplicateKey(Exception):
    pass


def _no_duplicates(pairs):
    seen = {}
    for k, v in pairs:
        if k in seen:
            raise _DuplicateKey(k)
        seen[k] = v
    return seen


def _reject_constant(name):
    raise ValueError(f'{name} is not valid JSON')


def words(s):
    return ' '.join(str(s).lower().split()).split(' ') if str(s).strip() else []


def appears_in(value, command):
    """True if value's words occur as a contiguous run of words in the command."""
    v, c = words(value), words(command)
    if not v:
        return False
    return any(c[i:i + len(v)] == v for i in range(len(c) - len(v) + 1))


def check(reply, command, intents):
    """Return (reason, parsed_object). reason is None when the record is acceptable."""
    try:
        obj = json.loads(str(reply).strip(), object_pairs_hook=_no_duplicates,
                         parse_constant=_reject_constant)
    except _DuplicateKey:
        return 'bad_keys', None
    except (json.JSONDecodeError, ValueError, TypeError):
        return 'invalid_json', None
    if not isinstance(obj, dict) or set(obj) != set(KEYS):
        return 'bad_keys', obj
    if not isinstance(obj['intent'], str) or obj['intent'] not in intents:
        return 'bad_intent', obj
    for k in SLOTS:
        v = obj[k]
        if v is None:
            continue
        if not isinstance(v, str) or not appears_in(v, command):
            return 'slot_not_in_text', obj
    return None, obj


def canonical(obj):
    return json.dumps({k: obj[k] for k in KEYS}, ensure_ascii=False)


def norm_text(t):
    return ' '.join(t.lower().split())


def clean(records, intents=DEFAULT_INTENTS):
    """records: iterable of {"id", "text", "teacher_raw"}. Return (kept, counts, rejected)."""
    records = sorted(records, key=lambda r: r['id'])
    counts = {'input': len(records), **{r: 0 for r in REASONS}, 'kept': 0}
    kept, rejected, seen = [], [], set()
    for r in records:
        reason, obj = check(r['teacher_raw'], r['text'], intents)
        if reason is None and norm_text(r['text']) in seen:
            reason = 'duplicate'
        if reason:
            counts[reason] += 1
            rejected.append({'id': r['id'], 'reason': reason})
            continue
        seen.add(norm_text(r['text']))
        kept.append({'id': r['id'], 'text': r['text'], 'teacher_raw': r['teacher_raw'],
                     'target': canonical(obj)})
    counts['kept'] = len(kept)
    assert counts['input'] == sum(counts[k] for k in REASONS) + counts['kept']
    return kept, counts, rejected


def read_shards(shards_uri):
    uris = [u for u in s3io.list_uris(shards_uri, suffix='.jsonl') if os.path.basename(u).startswith('shard-')]
    if not uris:
        sys.exit(f'no shard-*.jsonl found under {shards_uri}')
    records, per_shard = [], {}
    for u in uris:
        n = 0
        for line in s3io.read_text(u).splitlines():
            if line.strip():
                records.append(json.loads(line))
                n += 1
        per_shard[os.path.basename(u)] = n
    return records, per_shard


def load_intents(schema_path):
    if schema_path and os.path.exists(schema_path):
        with open(schema_path, encoding='utf-8') as f:
            return tuple(json.load(f)['intents'])
    return DEFAULT_INTENTS


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--shards', default='s3://datasets/teacher/', help='prefix or directory with shard-*.jsonl')
    ap.add_argument('--out', default='s3://datasets/v1/', help='prefix or directory for train.jsonl and train.sha256')
    ap.add_argument('--schema', default=os.environ.get('SCHEMA_FILE', 'data/schema.json'))
    ap.add_argument('--stats', help='also write the counts (and rejected ids) to this local JSON file')
    a = ap.parse_args()

    records, per_shard = read_shards(a.shards)
    ids = [r['id'] for r in records]
    repeated_ids = sorted({i for i in ids if ids.count(i) > 1}) if len(set(ids)) != len(ids) else []
    if repeated_ids:
        sys.exit(f'the same id appears more than once across shards: {repeated_ids[:10]}')
    kept, counts, rejected = clean(records, load_intents(a.schema))

    body = ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in kept).encode('utf-8')
    digest = hashlib.sha256(body).hexdigest()
    s3io.write_bytes(s3io.join(a.out, 'train.jsonl'), body)
    s3io.write_text(s3io.join(a.out, 'train.sha256'), f'{digest}  train.jsonl\n')

    raw_equals_target = sum(1 for r in kept if r['teacher_raw'].strip() == r['target'])
    print(f'shards: {per_shard}')
    print(f'{"input records":<34}{counts["input"]:>6}')
    for label, k in (('(a) not valid JSON', 'invalid_json'), ('(b) keys not exactly the four', 'bad_keys'),
                     ('(c) intent not one of the eight', 'bad_intent'),
                     ('(d) slot value not in the command', 'slot_not_in_text'),
                     ('(e) duplicate command', 'duplicate'), ('kept', 'kept')):
        print(f'{label:<34}{counts[k]:>6}')
    print(f'kept records whose raw reply is already canonical: {raw_equals_target}/{len(kept)}')
    print(f'sha256 {digest}  train.jsonl -> {s3io.join(a.out, "train.jsonl")}')
    if a.stats:
        s3io.write_text(a.stats, json.dumps({'counts': counts, 'per_shard': per_shard, 'sha256': digest,
                                             'raw_already_canonical': raw_equals_target,
                                             'rejected': rejected}, indent=2) + '\n')


if __name__ == '__main__':
    main()
