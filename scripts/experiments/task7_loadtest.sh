#!/usr/bin/env bash
# Task 7: the standard load test (exact assessment command) with `kubectl top pods` sampled during it.
source "$(dirname "$0")/lib.sh"
OUT=$RESULTS/task7
mkdir -p "$OUT"
LOG=$OUT/task7.log
: > "$LOG"
set_hpa_min 1
watch_cluster "$OUT/timeline.log" 5
( while true; do echo "# $(ts)"; kubectl top pods -n app --no-headers 2>&1; sleep 10; done ) > "$OUT/top_pods.log" 2>&1 &
TOP=$!
log "locust -f tools/locustfile.py --headless --users 4 --spawn-rate 4 --run-time 2m --host $INGRESS --csv $RESULTS/loadtest"
LOADTEST_HEADERS_OUT="$RESULTS/loadtest_headers.json" "$LOCUST" -f tools/locustfile.py --headless --users 4 --spawn-rate 4 --run-time 2m \
  --host "$INGRESS" --csv "$RESULTS/loadtest" 2>&1 | tee "$OUT/locust_stdout.log" || true
sleep 10
kill "$TOP" 2>/dev/null || true
stop_watch
cp "$RESULTS/loadtest_headers.json" "$OUT/" 2>/dev/null || true
log "summary: $(summarise_locust "$RESULTS")"
RESULTS="$RESULTS" "$PY" scripts/experiments/task7_report.py | tee "$OUT/summary.txt"
