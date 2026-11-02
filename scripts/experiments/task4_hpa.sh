#!/usr/bin/env bash
# Task 4.4: show the HPA scaling from 1 to 2 replicas under load and back down to 1 afterwards.
source "$(dirname "$0")/lib.sh"
OUT=$RESULTS/task4/hpa
mkdir -p "$OUT"
LOG=$OUT/hpa.log
: > "$LOG"
set_hpa_min 1
log "waiting for the HPA to settle at 1 replica (no load)"
wait_ready_replicas 1 900
watch_cluster "$OUT/timeline.log" 5
log "load on: 4 users for ${HPA_LOAD_TIME:-4m}"
locust_bg "$OUT" "${HPA_LOAD_TIME:-4m}"
locust_wait
log "load off: $(summarise_locust "$OUT")"
log "waiting for the scale-down to 1 replica"
wait_ready_replicas 1 900 || true
sleep 10
stop_watch
kubectl -n app describe hpa parser > "$OUT/describe_hpa.txt"
kubectl -n app get events --sort-by=.lastTimestamp | grep -iE 'horizontalpodautoscaler|scaled' > "$OUT/scaling_events.txt" || true
log "max replicas seen: $(grep -o 'deploy=[0-9]*/[0-9]*' "$OUT/timeline.log" | cut -d/ -f2 | sort -n | tail -1)"
