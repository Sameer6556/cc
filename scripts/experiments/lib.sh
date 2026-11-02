# Shared helpers for the experiment scripts (sourced, not executed).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
INGRESS=${INGRESS:-http://localhost:8080}
LOCUST=${LOCUST:-.venv-locust/bin/locust}
PY=${PY:-.venv/bin/python}
NS=app
RESULTS=${RESULTS:-results}

ts() { date -u +%Y-%m-%dT%H:%M:%S.%3NZ; }
log() { echo "[$(ts)] $*" | tee -a "${LOG:-/dev/null}"; }

# locust_bg OUTDIR RUN_TIME : the standard load test (4 users, spawn rate 4) in the background.
locust_bg() {
  local out=$1 run_time=$2
  mkdir -p "$out"
  LOADTEST_HEADERS_OUT="$out/loadtest_headers.json" \
    "$LOCUST" -f tools/locustfile.py --headless --users 4 --spawn-rate 4 --run-time "$run_time" \
    --host "$INGRESS" --csv "$out/loadtest" > "$out/locust_stdout.log" 2>&1 &
  LOCUST_PID=$!
}

locust_wait() { wait "$LOCUST_PID" || true; }  # Locust exits 1 if any request failed; we read the numbers

# ready_endpoints : number of ready endpoints behind the parser Service
ready_endpoints() {
  kubectl -n "$NS" get endpointslices -l kubernetes.io/service-name=parser -o json |
    "$PY" -c 'import json,sys; d=json.load(sys.stdin); print(sum(1 for s in d["items"] for e in (s.get("endpoints") or []) if (e.get("conditions") or {}).get("ready")))'
}

# watch_cluster FILE INTERVAL : background timeline of replicas, pods, endpoints and the HPA
watch_cluster() {
  local file=$1 interval=${2:-2}
  (
    while true; do
      echo "$(ts) deploy=$(kubectl -n "$NS" get deploy parser -o jsonpath='{.status.readyReplicas}/{.spec.replicas}' 2>/dev/null)" \
           "ready_endpoints=$(ready_endpoints 2>/dev/null)" \
           "hpa=$(kubectl -n "$NS" get hpa parser -o jsonpath='{.status.currentMetrics[0].resource.current.averageUtilization}%/{.status.desiredReplicas}' 2>/dev/null)" \
           "pods=[$(kubectl -n "$NS" get pods -l app=parser --no-headers -o custom-columns=N:.metadata.name,R:.status.containerStatuses[0].ready,P:.status.phase,D:.metadata.deletionTimestamp 2>/dev/null | tr -s ' ' | tr '\n' ';')]"
      sleep "$interval"
    done
  ) >> "$file" 2>&1 &
  WATCH_PID=$!
}

stop_watch() { kill "${WATCH_PID:-}" 2>/dev/null || true; }

# set_hpa_min N : change the HPA's minimum (used to hold exactly two replicas for a test)
set_hpa_min() { kubectl -n "$NS" patch hpa parser --type merge -p "{\"spec\":{\"minReplicas\":$1}}" >/dev/null; }

wait_ready_replicas() {  # wait_ready_replicas N TIMEOUT
  local n=$1 timeout=${2:-600} start
  start=$(date +%s)
  until [ "$(kubectl -n "$NS" get deploy parser -o jsonpath='{.status.readyReplicas}')" = "$n" ] &&
        [ "$(kubectl -n "$NS" get deploy parser -o jsonpath='{.status.replicas}')" = "$n" ]; do
    [ $(( $(date +%s) - start )) -gt "$timeout" ] && { log "timeout waiting for $n ready replicas"; return 1; }
    sleep 3
  done
}

# summarise_locust OUTDIR : one line with requests, failures, p50, p95, rps from loadtest_stats.csv
summarise_locust() {
  "$PY" - "$1" <<'EOF'
import csv, json, sys
out = sys.argv[1]
rows = {r['Name']: r for r in csv.DictReader(open(f'{out}/loadtest_stats.csv'))}
a = rows['Aggregated']
n, f = int(a['Request Count']), int(a['Failure Count'])
s = {'requests': n, 'failures': f, 'failure_pct': round(100.0 * f / n, 3) if n else None,
     'p50_ms': float(a['50%']), 'p95_ms': float(a['95%']), 'rps': round(float(a['Requests/s']), 3)}
try:
    s['headers'] = json.load(open(f'{out}/loadtest_headers.json'))
except FileNotFoundError:
    pass
print(json.dumps(s))
EOF
}
