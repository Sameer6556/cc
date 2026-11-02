#!/usr/bin/env bash
# Task 4.5: while the load test runs, roll the Deployment from v1 to v2 (MODEL_VERSION and MODEL_URI),
# then roll back with `kubectl rollout undo`. Report the failed-request rate and the versions served.
source "$(dirname "$0")/lib.sh"
OUT=$RESULTS/task4/rolling
mkdir -p "$OUT"
LOG=$OUT/rolling.log
: > "$LOG"
wait_ready_replicas "$(kubectl -n app get deploy parser -o jsonpath='{.spec.replicas}')" 600
kubectl -n app rollout history deploy/parser > "$OUT/history_before.txt"
watch_cluster "$OUT/timeline.log" 2
# sample which version answers, every second, alongside the load test
( while true; do
    v=$(curl -s -o /dev/null -D - -X POST "$INGRESS/parse" -H 'Content-Type: application/json' -d '{"text":"what time is it"}' |
        tr -d '\r' | awk -F': ' 'tolower($1)=="x-model-version"{print $2}' || true)
    echo "$(ts) X-Model-Version=${v:-none}"; sleep 1
  done ) > "$OUT/version_timeline.log" 2>&1 &
SAMPLER=$!
locust_bg "$OUT" "${ROLL_LOAD_TIME:-5m}"
sleep 40
log "rolling update: MODEL_VERSION=v2 MODEL_URI=s3://models/v2/"
kubectl -n app set env deploy/parser MODEL_VERSION=v2 MODEL_URI=s3://models/v2/ | tee -a "$LOG"
kubectl -n app rollout status deploy/parser --timeout=600s | tee -a "$LOG"
log "rollout to v2 complete"
sleep 45
log "rollback: kubectl rollout undo"
kubectl -n app rollout undo deploy/parser | tee -a "$LOG"
kubectl -n app rollout status deploy/parser --timeout=600s | tee -a "$LOG"
log "rollback complete"
locust_wait
kill "$SAMPLER" 2>/dev/null || true
stop_watch
log "load test: $(summarise_locust "$OUT")"
kubectl -n app rollout history deploy/parser > "$OUT/history_after.txt"
{
  echo "# $(ts) after the rollback: five requests through the Ingress"
  for i in 1 2 3 4 5; do
    curl -sS -i -X POST "$INGRESS/parse" -H 'Content-Type: application/json' -d '{"text": "set an alarm for six am"}' |
      tr -d '\r' | grep -iE '^(HTTP|x-model-version|x-served-by)'
  done
  echo "# env of the running Deployment"
  kubectl -n app get deploy parser -o jsonpath='{range .spec.template.spec.containers[0].env[*]}{.name}={.value}{"\n"}{end}'
} | tee "$OUT/after_rollback.txt"
