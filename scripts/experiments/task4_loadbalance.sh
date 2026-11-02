#!/usr/bin/env bash
# Task 4.8: with exactly two Ready replicas, run the standard load test through the Ingress and count
# the successful requests each replica served (X-Served-By, counted by tools/locustfile.py).
source "$(dirname "$0")/lib.sh"
OUT=$RESULTS/task4/loadbalance
mkdir -p "$OUT"
LOG=$OUT/loadbalance.log
: > "$LOG"
set_hpa_min 2
wait_ready_replicas 2 600
kubectl -n app get pods -l app=parser -o wide | tee -a "$LOG"
watch_cluster "$OUT/timeline.log" 5
locust_bg "$OUT" 2m
locust_wait
stop_watch
set_hpa_min 1
log "load test: $(summarise_locust "$OUT")"
"$PY" - "$OUT" <<'EOF' | tee -a "$LOG"
import json, sys
h = json.load(open(f'{sys.argv[1]}/loadtest_headers.json'))['per_replica']
total = sum(h.values())
for pod, n in sorted(h.items()):
    print(f'{pod}: {n} requests = {100.0 * n / total:.1f} % of {total} successful requests')
print('every replica served at least 30 %:', all(n / total >= 0.30 for n in h.values()) and len(h) == 2)
EOF
