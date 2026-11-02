"""Fine-tune Pythia-70M on the teacher's replies: sequence-level knowledge distillation (Task 2).

  make train                      python training/train.py --config training/config.yaml
  make train SUBSET=50            ... --subset 50            (first 50 records only, a smoke test)
  make train MODEL_VERSION=v2     ... --version v2           (applies the v2 overrides in the config)

Every hyper-parameter comes from the config file. Each training example is
    "Command: <the command>\\nJSON: <the teacher's JSON reply><|endoftext|>"
and the loss is computed only on the reply tokens (the command is context, not a target), so the
student learns to reproduce the teacher's output given the command. The seed is fixed in code via
set_seed() before anything random happens, and torch runs in deterministic mode.
"""
import argparse
import csv
import hashlib
import json
import os
import platform
import random
import subprocess
import sys
import time
from importlib import metadata

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'service'))

from parser_core import build_prompt, build_target  # noqa: E402


def load_config(path, version):
    with open(path, encoding='utf-8') as f:
        cfg = yaml.safe_load(f)
    overrides = (cfg.get('versions') or {}).get(version)
    if overrides is None:
        sys.exit(f'version {version!r} is not defined under "versions" in {path}')
    cfg = {k: v for k, v in cfg.items() if k != 'versions'}
    cfg.update(overrides)
    cfg['version'] = version
    return cfg


def check_libraries(expected):
    """Warn (do not fail) when installed versions differ from the ones recorded in the config."""
    found = {'python': platform.python_version()}
    for name in expected:
        if name != 'python':
            try:
                found[name] = metadata.version(name)
            except metadata.PackageNotFoundError:
                found[name] = None
    for name, want in expected.items():
        have = found.get(name) or ''
        if not have.startswith(str(want)):
            print(f'WARNING: {name} {have!r} is installed but the config records {want!r}', flush=True)
    return found


def set_seed(seed):
    import numpy as np
    import torch

    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.use_deterministic_algorithms(True)


def read_records(path, limit):
    rows = []
    with open(path, encoding='utf-8') as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
                if len(rows) == limit:
                    break
    return rows


def encode(tokenizer, rec, max_len):
    """Token ids and labels for one example; labels are -100 on the prompt (no loss there)."""
    prompt_ids = tokenizer.encode(build_prompt(rec['text']), add_special_tokens=False)
    target_ids = tokenizer.encode(build_target(rec['target']), add_special_tokens=False) + [tokenizer.eos_token_id]
    ids = (prompt_ids + target_ids)[:max_len]
    labels = ([-100] * len(prompt_ids) + target_ids)[:max_len]
    return ids, labels, len(prompt_ids) + len(target_ids) > max_len


def batches(examples, batch_size, generator, pad_id):
    import torch

    order = torch.randperm(len(examples), generator=generator).tolist()
    for i in range(0, len(order), batch_size):
        chunk = [examples[j] for j in order[i:i + batch_size]]
        width = max(len(ids) for ids, _ in chunk)
        input_ids = torch.full((len(chunk), width), pad_id, dtype=torch.long)
        labels = torch.full((len(chunk), width), -100, dtype=torch.long)
        mask = torch.zeros((len(chunk), width), dtype=torch.long)
        for r, (ids, lab) in enumerate(chunk):
            input_ids[r, :len(ids)] = torch.tensor(ids)
            labels[r, :len(lab)] = torch.tensor(lab)
            mask[r, :len(ids)] = 1
        yield {'input_ids': input_ids, 'attention_mask': mask, 'labels': labels}


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def git_commit():
    try:
        return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True,
                                       stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--config', default=os.path.join(ROOT, 'training', 'config.yaml'))
    ap.add_argument('--version', default='v1')
    ap.add_argument('--subset', type=int, default=0, help='train on the first N records only (smoke test)')
    a = ap.parse_args()

    cfg = load_config(a.config, a.version)
    libs = check_libraries(cfg['libraries'])
    set_seed(cfg['seed'])  # the seed is fixed here, before the model, data order or dropout use randomness

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, get_linear_schedule_with_warmup
    from huggingface_hub import HfApi

    torch.set_num_threads(cfg['num_threads'])
    limit = min(cfg['max_train_records'], a.subset) if a.subset else cfg['max_train_records']
    train_file = os.path.join(ROOT, cfg['train_file'])
    records = read_records(train_file, limit)
    out_dir = os.path.join(ROOT, cfg['output_dir'] + ('-subset' if a.subset else ''))
    loss_csv = os.path.join(ROOT, cfg['loss_csv'])
    if a.subset:
        loss_csv = loss_csv.replace('.csv', f'_subset{a.subset}.csv')

    revision = cfg['base_model_revision']
    try:  # record the exact commit of the base model that was downloaded
        resolved = HfApi().model_info(cfg['base_model'], revision=revision).sha
    except Exception as e:  # noqa: BLE001 - offline runs still work from the local cache
        print(f'could not resolve the base model revision ({e!r})', flush=True)
        resolved = revision
    tokenizer = AutoTokenizer.from_pretrained(cfg['base_model'], revision=resolved)
    model = AutoModelForCausalLM.from_pretrained(cfg['base_model'], revision=resolved, dtype=torch.float32)
    model.train()

    examples, truncated = [], 0
    for rec in records:
        ids, labels, cut = encode(tokenizer, rec, cfg['max_seq_len'])
        examples.append((ids, labels))
        truncated += cut
    steps_per_epoch = (len(examples) + cfg['batch_size'] - 1) // cfg['batch_size']
    total_steps = steps_per_epoch * cfg['epochs']
    optimizer = torch.optim.AdamW(model.parameters(), lr=cfg['learning_rate'], weight_decay=cfg['weight_decay'])
    scheduler = get_linear_schedule_with_warmup(optimizer, int(cfg['warmup_ratio'] * total_steps), total_steps)
    generator = torch.Generator().manual_seed(cfg['seed'])
    print(json.dumps({'event': 'start', 'version': cfg['version'], 'records': len(records), 'truncated': truncated,
                      'first_id': records[0]['id'], 'last_id': records[-1]['id'], 'epochs': cfg['epochs'],
                      'steps': total_steps, 'base_model': cfg['base_model'], 'revision': resolved,
                      'threads': torch.get_num_threads()}), flush=True)

    os.makedirs(os.path.dirname(loss_csv), exist_ok=True)
    history, t0 = [], time.time()
    for epoch in range(1, cfg['epochs'] + 1):
        total, tokens = 0.0, 0
        for batch in batches(examples, cfg['batch_size'], generator, tokenizer.eos_token_id):
            out = model(**batch)
            optimizer.zero_grad(set_to_none=True)
            out.loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), cfg['grad_clip'])
            optimizer.step()
            scheduler.step()
            n = int((batch['labels'][:, 1:] != -100).sum())  # tokens that carried loss in this batch
            total += out.loss.item() * n
            tokens += n
        history.append((epoch, total / tokens))
        with open(loss_csv, 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            w.writerow(['epoch', 'loss'])
            w.writerows((e, f'{loss:.6f}') for e, loss in history)
        print(json.dumps({'event': 'epoch', 'epoch': epoch, 'loss': round(total / tokens, 6),
                          'elapsed_s': round(time.time() - t0, 1)}), flush=True)

    model.eval()
    os.makedirs(out_dir, exist_ok=True)
    model.save_pretrained(out_dir, safe_serialization=True)
    tokenizer.save_pretrained(out_dir)
    info = {
        'version': cfg['version'] + ('-subset' if a.subset else ''),
        'base_model': cfg['base_model'],
        'base_model_revision': resolved,
        'train_file': cfg['train_file'],
        'train_file_sha256': sha256_file(train_file),
        'records': len(records),
        'first_id': records[0]['id'],
        'last_id': records[-1]['id'],
        'hyperparameters': {k: cfg[k] for k in ('seed', 'learning_rate', 'batch_size', 'epochs', 'max_seq_len',
                                                'weight_decay', 'warmup_ratio', 'grad_clip', 'num_threads')},
        'libraries_expected': cfg['libraries'],
        'libraries_installed': libs,
        'loss_per_epoch': [round(loss, 6) for _, loss in history],
        'train_seconds': round(time.time() - t0, 1),
        'git_commit': git_commit(),
        'created_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    }
    with open(os.path.join(out_dir, 'version.json'), 'w', encoding='utf-8') as f:
        json.dump(info, f, indent=2)
        f.write('\n')
    print(json.dumps({'event': 'saved', 'dir': out_dir, 'loss_csv': loss_csv,
                      'train_seconds': info['train_seconds']}), flush=True)


if __name__ == '__main__':
    main()
