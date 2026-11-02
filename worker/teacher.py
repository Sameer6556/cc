"""Client for the teacher model (phi3.5 served by Ollama).

The decoding settings required by the assignment are fixed here and cannot be overridden:
temperature 0 and seed 42. The reply text is returned exactly as Ollama produced it.
"""
import json
import time
import urllib.error
import urllib.request

TEACHER_MODEL = 'phi3.5'
TEMPERATURE = 0
SEED = 42
# Generation ends at a blank line or when the model starts another "Command:" line. A frame is one
# line, so this only cuts off trailing chatter; the stored reply is still exactly what was generated.
STOP = ['\n\n', '\nCommand:']


def load_prompt(path):
    with open(path, encoding='utf-8') as f:
        template = f.read()
    if '{command}' not in template:
        raise ValueError(f'{path} must contain the placeholder {{command}}')
    return template


def build_prompt(template, command):
    # str.format cannot be used: the template contains literal JSON braces.
    return template.replace('{command}', command)


def options(num_predict, num_ctx):
    return {'temperature': TEMPERATURE, 'seed': SEED, 'num_predict': num_predict, 'num_ctx': num_ctx, 'stop': STOP}


def generate(base_url, prompt, model=TEACHER_MODEL, num_predict=128, num_ctx=2048,
             timeout=600, retries=8):
    """Send one prompt to Ollama's /api/generate. Return (reply_text, metadata)."""
    body = json.dumps({
        'model': model,
        'prompt': prompt,
        'stream': False,
        'keep_alive': '24h',
        'options': options(num_predict, num_ctx),
    }).encode('utf-8')
    url = base_url.rstrip('/') + '/api/generate'
    delay = 2.0
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(url, data=body, headers={'Content-Type': 'application/json'})
        try:
            t0 = time.time()
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            meta = {
                'seconds': round(time.time() - t0, 3),
                'prompt_tokens': data.get('prompt_eval_count'),
                'reply_tokens': data.get('eval_count'),
                'done_reason': data.get('done_reason'),
            }
            return data['response'], meta
        except (urllib.error.URLError, ConnectionError, TimeoutError, KeyError) as e:
            if attempt == retries:
                raise
            print(f'teacher request failed ({e!r}); retry {attempt}/{retries} in {delay:.0f}s', flush=True)
            time.sleep(delay)
            delay = min(delay * 2, 60)


def wait_until_ready(base_url, model=TEACHER_MODEL, timeout=1800):
    """Block until Ollama answers and lists the model (it may still be pulling it)."""
    deadline = time.time() + timeout
    url = base_url.rstrip('/') + '/api/tags'
    while True:
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                names = [m.get('name', '') for m in json.loads(resp.read().decode('utf-8')).get('models', [])]
            if any(n == model or n.startswith(model + ':') for n in names):
                return names
            print(f'ollama is up but {model} is not pulled yet: {names}', flush=True)
        except Exception as e:  # noqa: BLE001 - any failure means "not ready yet"
            print(f'waiting for ollama at {base_url}: {e!r}', flush=True)
        if time.time() > deadline:
            raise TimeoutError(f'ollama at {base_url} not ready after {timeout}s')
        time.sleep(10)
