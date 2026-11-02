"""Model-side logic shared by training, offline evaluation and the web service.

Keeping the prompt format, decoding and validation in one module guarantees that the numbers
measured offline (training/predict.py) are produced exactly the way the service produces them.
"""
import json
import math
import os

# Training example layout (Task 2):  "Command: <the command>\nJSON: <the teacher's JSON reply>"
# The prompt stops after "JSON:" and the target starts with the space, so the tokenizer sees
# the natural " {" token at the boundary both in training and at inference time.
PROMPT_PREFIX = 'Command: '
PROMPT_SUFFIX = '\nJSON:'
KEYS = ('intent', 'date', 'time', 'place')


def build_prompt(text):
    return PROMPT_PREFIX + text + PROMPT_SUFFIX


def build_target(target_json):
    return ' ' + target_json


def cpu_limit():
    """CPUs this process may use: the cgroup CPU limit if there is one, else the CPU count."""
    try:  # cgroup v2
        with open('/sys/fs/cgroup/cpu.max') as f:
            quota, period = f.read().split()
        if quota != 'max':
            return max(1, math.ceil(int(quota) / int(period)))
    except (OSError, ValueError):
        pass
    try:  # cgroup v1
        with open('/sys/fs/cgroup/cpu/cpu.cfs_quota_us') as f:
            quota = int(f.read())
        with open('/sys/fs/cgroup/cpu/cpu.cfs_period_us') as f:
            period = int(f.read())
        if quota > 0:
            return max(1, math.ceil(quota / period))
    except (OSError, ValueError):
        pass
    return os.cpu_count() or 1


def load_schema(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def validate(raw, schema):
    """Return the parsed object if raw is a JSON object that satisfies schema.json, else None."""
    import jsonschema

    try:
        obj = json.loads(str(raw).strip(), parse_constant=lambda c: (_ for _ in ()).throw(ValueError(c)))
    except (json.JSONDecodeError, ValueError, TypeError):
        return None
    try:
        jsonschema.validate(obj, schema['json_schema'])
    except jsonschema.ValidationError:
        return None
    return {k: obj[k] for k in KEYS}


class Parser:
    """A causal LM that maps a command to the raw text of its JSON frame (greedy decoding)."""

    def __init__(self, model_dir, revision=None, num_threads=None):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        torch.set_num_threads(num_threads or cpu_limit())
        self.torch = torch
        self.tokenizer = AutoTokenizer.from_pretrained(model_dir, revision=revision)
        self.model = AutoModelForCausalLM.from_pretrained(model_dir, revision=revision, dtype=torch.float32)
        self.model.eval()
        self.eos_id = self.tokenizer.eos_token_id
        newline = self.tokenizer.encode('\n', add_special_tokens=False)
        # Stop at end-of-text, or at a newline: a frame is always a single line.
        self.stop_ids = [self.eos_id] + ([newline[0]] if len(newline) == 1 else [])

    def generate(self, text, max_new_tokens=64):
        enc = self.tokenizer(build_prompt(text), return_tensors='pt')
        with self.torch.inference_mode():
            out = self.model.generate(
                **enc,
                max_new_tokens=max_new_tokens,
                do_sample=False,
                num_beams=1,
                eos_token_id=self.stop_ids,
                pad_token_id=self.eos_id,
            )
        new_tokens = out[0, enc['input_ids'].shape[1]:]
        reply = self.tokenizer.decode(new_tokens, skip_special_tokens=True, clean_up_tokenization_spaces=False)
        return reply.split('\n', 1)[0].strip()
