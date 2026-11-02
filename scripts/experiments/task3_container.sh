#!/usr/bin/env bash
# Task 3: the image (size, no weights inside) and the container under limits: 1 CPU, 1 GiB memory.
# Sends 50 sequential requests, records peak memory, then checks FAULT_INJECT=1.
# Needs the cluster's object store (make up) because the container downloads the model at start-up.
source "$(dirname "$0")/lib.sh"
OUT=$RESULTS/task3
IMAGE=${IMAGE:-parser-service:0.1.0}
PORT=${PORT:-18000}
mkdir -p "$OUT"
LOG=$OUT/task3.log
: > "$LOG"
source .secrets/s3.env
ENVFILE=$(mktemp)
chmod 600 "$ENVFILE"
cat > "$ENVFILE" <<EOF
MODEL_URI=s3://models/v1/
MODEL_VERSION=v1
S3_ENDPOINT=http://127.0.0.1:30333
MAX_NEW_TOKENS=64
AWS_ACCESS_KEY_ID=$S3_READER_ACCESS_KEY
AWS_SECRET_ACCESS_KEY=$S3_READER_SECRET_KEY
EOF

{
  echo "# $(ts) docker image ls $IMAGE"; docker image ls "$IMAGE"
  echo "size_bytes=$(docker image inspect -f '{{.Size}}' "$IMAGE")"
  echo; echo "# docker history"; docker history --no-trunc --format '{{.Size}}\t{{.CreatedBy}}' "$IMAGE" | cut -c1-220
} > "$OUT/image.txt"
{
  echo "# $(ts) files that could be model weights inside the image (expect none):"
  docker run --rm --entrypoint sh "$IMAGE" -c \
    "find / -xdev \( -name '*.safetensors' -o -name 'pytorch_model*.bin' -o -name '*.gguf' -o -name 'tokenizer.json' \) 2>/dev/null | grep -v '^/proc' || true"
  echo "# (end of list)"
} > "$OUT/no_weights_in_image.txt"

run_container() {  # run_container NAME EXTRA_ENV...
  local name=$1; shift
  docker rm -f "$name" >/dev/null 2>&1 || true
  docker run -d --name "$name" --network host --cpus 1 --memory 1g --memory-swap 1g \
    --env-file "$ENVFILE" "$@" "$IMAGE" \
    uvicorn app:app --host 127.0.0.1 --port "$PORT" --no-access-log >/dev/null
}

log "starting $IMAGE with --cpus 1 --memory 1g --memory-swap 1g"
run_container parser-limits
( while docker inspect parser-limits >/dev/null 2>&1; do
    echo "$(ts) $(docker stats --no-stream --format '{{.MemUsage}} {{.CPUPerc}}' parser-limits)"; sleep 0.5
  done ) > "$OUT/docker_stats.log" 2>&1 &
STATS=$!
{
  for i in $(seq 1 120); do
    code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/readyz" || true)
    echo "$(ts) GET /readyz -> ${code}  GET /healthz -> $(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/healthz" || true)"
    [ "$code" = 200 ] && break
    sleep 0.5
  done
} > "$OUT/readiness.log"
{
  echo "# $(ts) curl -i GET /healthz"; curl -sS -i "http://127.0.0.1:$PORT/healthz"; echo
  echo "# curl -i GET /readyz"; curl -sS -i "http://127.0.0.1:$PORT/readyz"; echo
  echo "# curl -i POST /parse"
  curl -sS -i -X POST "http://127.0.0.1:$PORT/parse" -H 'Content-Type: application/json' -d '{"text": "set an alarm for seven thirty am tomorrow"}'; echo
} > "$OUT/endpoints.txt" 2>&1

log "50 sequential requests"
"$PY" - "$PORT" <<'EOF' > "$OUT/sequential_50.txt"
import json, sys, time, urllib.request, urllib.error
port = sys.argv[1]
texts = [json.loads(l)['text'] for l in open('data/validation.jsonl')][:50]
codes, lat = {}, []
for i, t in enumerate(texts, 1):
    req = urllib.request.Request(f'http://127.0.0.1:{port}/parse', data=json.dumps({'text': t}).encode(),
                                 headers={'Content-Type': 'application/json'})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            code, body = r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        code, body = e.code, e.read().decode()
    lat.append(time.time() - t0)
    codes[code] = codes.get(code, 0) + 1
    print(f'{i:2d} {code} {lat[-1]*1000:7.1f} ms  {t!r} -> {body}')
lat.sort()
print(f'status codes: {codes}; completed {len(lat)}/50; mean {sum(lat)/len(lat)*1000:.0f} ms, '
      f'median {lat[len(lat)//2]*1000:.0f} ms, max {lat[-1]*1000:.0f} ms')
EOF
tail -1 "$OUT/sequential_50.txt" | tee -a "$LOG"
{
  echo "# $(ts) after the 50 requests"
  echo "OOMKilled=$(docker inspect -f '{{.State.OOMKilled}}' parser-limits) Running=$(docker inspect -f '{{.State.Running}}' parser-limits) RestartCount=$(docker inspect -f '{{.RestartCount}}' parser-limits)"
  echo "limits: NanoCpus=$(docker inspect -f '{{.HostConfig.NanoCpus}}' parser-limits) Memory=$(docker inspect -f '{{.HostConfig.Memory}}' parser-limits)"
  echo "cgroup memory peak (bytes): $(docker exec parser-limits sh -c 'cat /sys/fs/cgroup/memory.peak 2>/dev/null || cat /sys/fs/cgroup/memory/memory.max_usage_in_bytes')"
  echo "cgroup memory current (bytes): $(docker exec parser-limits sh -c 'cat /sys/fs/cgroup/memory.current 2>/dev/null || cat /sys/fs/cgroup/memory/memory.usage_in_bytes')"
  echo "highest docker stats sample: $(awk '{print $2, $3, $4}' "$OUT/docker_stats.log" | sort -h | tail -1)"
} | tee "$OUT/memory_peak.txt"
docker logs parser-limits > "$OUT/container.log" 2>&1
kill "$STATS" 2>/dev/null || true
docker rm -f parser-limits >/dev/null

log "FAULT_INJECT=1"
run_container parser-fault -e FAULT_INJECT=1
for i in $(seq 1 120); do [ "$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/readyz")" = 200 ] && break; sleep 0.5; done
{
  echo "# $(ts) FAULT_INJECT=1: POST /parse"
  curl -sS -i -X POST "http://127.0.0.1:$PORT/parse" -H 'Content-Type: application/json' -d '{"text": "what is the weather in london"}'; echo
} | tee "$OUT/fault_inject.txt"
docker rm -f parser-fault >/dev/null
rm -f "$ENVFILE"
