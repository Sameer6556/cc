#!/usr/bin/env bash
# Task 4.6: while the load test runs, delete one Pod and show the replica count coming back.
# The HPA minimum is held at 2 during the test so that there are two replicas to begin with.
source "$(dirname "$0")/lib.sh"
OUT=$RESULTS/task4/recovery
mkdir -p "$OUT"
LOG=$OUT/recovery.log
: > "$LOG"
set_hpa_min 2
wait_ready_replicas 2 600
watch_cluster "$OUT/timeline.log" 1
locust_bg "$OUT" "${RECOVERY_LOAD_TIME:-3m}"
sleep 45
victim=$(kubectl -n app get pods -l app=parser -o jsonpath='{.items[0].metadata.name}')
log "deleting pod $victim"
t0=$(date +%s%N)
kubectl -n app delete pod "$victim" --wait=false | tee -a "$LOG"
until [ "$(kubectl -n app get deploy parser -o jsonpath='{.status.readyReplicas}')" = 2 ] &&
      ! kubectl -n app get pod "$victim" >/dev/null 2>&1; do sleep 0.5; done
t1=$(date +%s%N)
log "replica count back to 2 ready, $(( (t1 - t0) / 1000000 )) ms after the deletion"
kubectl -n app get pods -l app=parser -o wide | tee -a "$LOG"
locust_wait
stop_watch
set_hpa_min 1
log "load test: $(summarise_locust "$OUT")"
