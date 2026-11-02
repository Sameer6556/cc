"""Teacher-labelling worker (Task 1).

Environment
  SHARD_INDEX   which shard this worker owns, counting from 0            (required)
  SHARD_COUNT   how many workers share the input                         (required)
  INPUT_URI     commands file, one JSON object per line                   default s3://datasets/commands_pool.jsonl
  OUTPUT_URI    where this shard's raw replies go; {shard} is replaced    default s3://datasets/teacher/shard-{shard}.jsonl
  PROMPT_FILE   teacher prompt with a {command} placeholder              default prompts/teacher_prompt.txt
  OLLAMA_URL    Ollama base URL                                           default http://ollama.pipeline.svc.cluster.local:11434
  NUM_PREDICT   maximum reply tokens                                      default 128
  NUM_CTX       context window passed to Ollama                           default 2048
  CHECKPOINT_EVERY  upload the partial shard every N replies              default 25
  LIMIT         optional: stop after N commands of this shard (for smoke tests)

The worker takes every command whose line number n (counting from 0) satisfies
n % SHARD_COUNT == SHARD_INDEX and writes one line per command:
  {"id": "...", "text": "...", "teacher_raw": "<the teacher's exact reply>"}
The reply is stored exactly as generated. If the output object already exists (for example
after a Pod restart) the worker keeps those lines and continues with the remaining commands.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import s3io  # noqa: E402
import teacher  # noqa: E402


def shard_of(lines, index, count):
    """Return [(line_number, record)] for the lines this shard owns. Blank lines keep their number."""
    if count < 1 or not 0 <= index < count:
        raise ValueError(f'need 0 <= SHARD_INDEX < SHARD_COUNT, got {index} and {count}')
    out = []
    for n, line in enumerate(lines):
        if n % count == index and line.strip():
            out.append((n, json.loads(line)))
    return out


def output_line(rec, reply):
    return json.dumps({'id': rec['id'], 'text': rec['text'], 'teacher_raw': reply}, ensure_ascii=False)


def load_done(output_uri):
    """Lines already written by an earlier run of this shard (resume after a restart)."""
    text = s3io.read_text(output_uri)
    if not text:
        return [], set()
    kept, ids = [], set()
    for line in text.splitlines():
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            break  # a torn last line: drop it and everything after it
        if not {'id', 'text', 'teacher_raw'} <= obj.keys():
            break
        kept.append(line)
        ids.add(obj['id'])
    return kept, ids


def env_int(name, default=None):
    v = os.environ.get(name)
    if v is None or v == '':
        if default is None:
            sys.exit(f'environment variable {name} is required')
        return default
    return int(v)


def main():
    index = env_int('SHARD_INDEX')
    count = env_int('SHARD_COUNT')
    input_uri = os.environ.get('INPUT_URI', 's3://datasets/commands_pool.jsonl')
    output_uri = os.environ.get('OUTPUT_URI', 's3://datasets/teacher/shard-{shard}.jsonl')
    output_uri = output_uri.replace('{shard}', str(index))
    prompt_file = os.environ.get('PROMPT_FILE', 'prompts/teacher_prompt.txt')
    ollama_url = os.environ.get('OLLAMA_URL', 'http://ollama.pipeline.svc.cluster.local:11434')
    num_predict = env_int('NUM_PREDICT', 128)
    num_ctx = env_int('NUM_CTX', 2048)
    every = env_int('CHECKPOINT_EVERY', 25)
    limit = env_int('LIMIT', 0)

    template = teacher.load_prompt(prompt_file)
    raw = s3io.read_text(input_uri)
    if raw is None:
        sys.exit(f'input {input_uri} not found')
    mine = shard_of(raw.splitlines(), index, count)
    if limit:
        mine = mine[:limit]
    lines, done = load_done(output_uri)
    todo = [(n, r) for n, r in mine if r['id'] not in done]
    print(json.dumps({'event': 'start', 'shard_index': index, 'shard_count': count, 'input': input_uri,
                      'output': output_uri, 'assigned': len(mine), 'already_done': len(done),
                      'todo': len(todo), 'model': teacher.TEACHER_MODEL,
                      'options': teacher.options(num_predict, num_ctx)}), flush=True)

    teacher.wait_until_ready(ollama_url)
    t_start = time.time()
    secs, reply_tokens = [], []
    for i, (n, rec) in enumerate(todo, 1):
        reply, meta = teacher.generate(ollama_url, teacher.build_prompt(template, rec['text']),
                                       num_predict=num_predict, num_ctx=num_ctx)
        lines.append(output_line(rec, reply))
        secs.append(meta['seconds'])
        reply_tokens.append(meta['reply_tokens'] or 0)
        if i % every == 0 or i == len(todo):
            s3io.write_text(output_uri, '\n'.join(lines) + '\n')
            elapsed = time.time() - t_start
            print(json.dumps({'event': 'progress', 'shard_index': index, 'done': len(lines),
                              'assigned': len(mine), 'last_id': rec['id'], 'line': n,
                              'mean_s_per_cmd': round(sum(secs) / len(secs), 2),
                              'mean_reply_tokens': round(sum(reply_tokens) / len(reply_tokens), 1),
                              'elapsed_s': round(elapsed), 'eta_s': round(elapsed / i * (len(todo) - i))}),
                  flush=True)
    if not todo:
        s3io.write_text(output_uri, '\n'.join(lines) + ('\n' if lines else ''))
    print(json.dumps({'event': 'finished', 'shard_index': index, 'written': len(lines),
                      'output': output_uri, 'seconds': round(time.time() - t_start, 1),
                      'mean_s_per_cmd': round(sum(secs) / len(secs), 2) if secs else None}), flush=True)


if __name__ == '__main__':
    main()
