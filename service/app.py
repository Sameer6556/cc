"""Command-parser inference service (Task 3).

Endpoints
  POST /parse    {"text": "..."} -> 200 and the four-key JSON object (nothing else in the body),
                 or 500 {"error": "invalid_model_output"} when the output fails schema.json.
                 Both carry the headers X-Model-Version and X-Served-By (the Pod name).
  GET  /healthz  200 while the process is alive.
  GET  /readyz   503 until the model is loaded, 200 after that.

Configuration (environment)
  MODEL_URI       where the model and tokenizer live in object storage, e.g. s3://models/v1/
  MODEL_VERSION   reported in X-Model-Version, e.g. v1
  S3_ENDPOINT     the object store, e.g. http://seaweedfs-s3.data.svc.cluster.local:8333
  MAX_NEW_TOKENS  generation budget per request
  FAULT_INJECT    "1" replaces the model output with the text "not json" before validation
Credentials (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY) come from a Kubernetes Secret, and
POD_NAME from the downward API. The image contains no weights: they are downloaded at start-up.
"""
import contextlib
import hashlib
import json
import logging
import os
import socket
import sys
import threading
import time

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from parser_core import Parser, cpu_limit, load_schema, validate  # noqa: E402

MODEL_URI = os.environ.get('MODEL_URI', '')
MODEL_VERSION = os.environ.get('MODEL_VERSION', 'unknown')
S3_ENDPOINT = os.environ.get('S3_ENDPOINT', '')
MAX_NEW_TOKENS = int(os.environ.get('MAX_NEW_TOKENS', '64'))
FAULT_INJECT = os.environ.get('FAULT_INJECT', '0') == '1'
POD_NAME = os.environ.get('POD_NAME') or socket.gethostname()
HERE = os.path.dirname(os.path.abspath(__file__))
# schema.json is copied next to app.py in the image; in a source checkout it is data/schema.json.
SCHEMA_PATH = next(p for p in (os.path.join(HERE, 'schema.json'), os.path.join(HERE, '..', 'data', 'schema.json'))
                   if os.path.exists(p))
MODEL_DIR = '/tmp/model'

logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                    format='%(asctime)s.%(msecs)03d %(levelname)s %(message)s', datefmt='%Y-%m-%dT%H:%M:%S')
log = logging.getLogger('parser')

SCHEMA = load_schema(SCHEMA_PATH)
STATE = {'parser': None, 'started': time.time()}
INFER_LOCK = threading.Lock()  # one generation at a time per Pod: predictable latency under a CPU limit
HEADERS = {'X-Model-Version': MODEL_VERSION, 'X-Served-By': POD_NAME}


def s3_client():
    import boto3
    from botocore.config import Config

    return boto3.client('s3', endpoint_url=S3_ENDPOINT, region_name=os.environ.get('AWS_REGION', 'us-east-1'),
                        config=Config(s3={'addressing_style': 'path'}, signature_version='s3v4',
                                      retries={'max_attempts': 5, 'mode': 'standard'}))


def download_model(uri, dest):
    """Download every object under s3://bucket/prefix/ into dest and verify model.sha256 if present."""
    if not uri.startswith('s3://'):
        raise ValueError(f'MODEL_URI must be an s3:// URI, got {uri!r}')
    bucket, _, prefix = uri[5:].partition('/')
    prefix = prefix.rstrip('/') + '/'
    client = s3_client()
    os.makedirs(dest, exist_ok=True)
    keys = [o['Key'] for page in client.get_paginator('list_objects_v2').paginate(Bucket=bucket, Prefix=prefix)
            for o in page.get('Contents', [])]
    if not keys:
        raise FileNotFoundError(f'no objects under {uri}')
    size = 0
    for key in keys:
        name = key[len(prefix):]
        if not name or '/' in name:
            continue
        client.download_file(bucket, key, os.path.join(dest, name))
        size += os.path.getsize(os.path.join(dest, name))
    sums = os.path.join(dest, 'model.sha256')
    checked = 0
    if os.path.exists(sums):
        for line in open(sums, encoding='utf-8'):
            if line.strip():
                digest, name = line.split(maxsplit=1)
                name = name.strip().lstrip('*')
                h = hashlib.sha256()
                with open(os.path.join(dest, name), 'rb') as f:
                    for block in iter(lambda: f.read(1 << 20), b''):
                        h.update(block)
                if h.hexdigest() != digest:
                    raise ValueError(f'checksum mismatch for {name}')
                checked += 1
    return len(keys), size, checked


def load_model_forever():
    """Runs in a background thread: retry until the model is downloaded and loaded."""
    delay = 2
    while True:
        try:
            t0 = time.time()
            log.info('downloading model from %s (endpoint %s, version %s)', MODEL_URI, S3_ENDPOINT, MODEL_VERSION)
            n, size, checked = download_model(MODEL_URI, MODEL_DIR)
            t1 = time.time()
            log.info('downloaded %d objects (%.1f MB) in %.2fs; %d checksums verified',
                     n, size / 1e6, t1 - t0, checked)
            parser = Parser(MODEL_DIR)
            parser.generate('wake me up at seven am', MAX_NEW_TOKENS)  # warm-up before we report ready
            STATE['parser'] = parser
            log.info('model loaded in %.2fs (torch threads %d); ready %.2fs after process start',
                     time.time() - t1, cpu_limit(), time.time() - STATE['started'])
            return
        except Exception as e:  # noqa: BLE001 - keep retrying; /readyz stays 503 meanwhile
            log.error('model load failed: %r; retrying in %ds', e, delay)
            time.sleep(delay)
            delay = min(delay * 2, 30)


@contextlib.asynccontextmanager
async def lifespan(app):
    log.info('starting pod=%s version=%s uri=%s max_new_tokens=%d fault_inject=%s',
             POD_NAME, MODEL_VERSION, MODEL_URI, MAX_NEW_TOKENS, FAULT_INJECT)
    threading.Thread(target=load_model_forever, daemon=True).start()
    yield
    log.info('shutting down')


app = FastAPI(title='command parser', lifespan=lifespan)


class ParseRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


@app.get('/healthz')
def healthz():
    return {'status': 'alive'}


@app.get('/readyz')
def readyz():
    if STATE['parser'] is None:
        return JSONResponse({'status': 'loading'}, status_code=503)
    return {'status': 'ready', 'model_version': MODEL_VERSION}


@app.post('/parse')
def parse(req: ParseRequest):
    parser = STATE['parser']
    if parser is None:
        return JSONResponse({'error': 'model_not_ready'}, status_code=503, headers=HEADERS)
    with INFER_LOCK:
        raw = parser.generate(req.text, MAX_NEW_TOKENS)
    if FAULT_INJECT:
        raw = 'not json'
    obj = validate(raw, SCHEMA)
    if obj is None:
        log.warning('invalid model output for %s: %s', json.dumps(req.text), json.dumps(raw))
        return JSONResponse({'error': 'invalid_model_output'}, status_code=500, headers=HEADERS)
    return JSONResponse(obj, headers=HEADERS)
