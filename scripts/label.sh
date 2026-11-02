#!/usr/bin/env bash
# Task 1: run the teacher-labelling pipeline in the cluster and collect the evidence.
#   Ollama (phi3.5) in namespace "pipeline" -> Indexed Job with 2 workers (SHARD_INDEX 0 and 1)
#   -> clean Job -> teacher evaluation Job on the validation texts -> copy results into the repo.
# Prerequisites: make cluster secrets storage seed-data worker-image
set -euo pipefail
cd "$(dirname "$0")/.."
OUT=${OUT:-results/task1}
PY=${PY:-.venv/bin/python}
LABEL_TIMEOUT=${LABEL_TIMEOUT:-21600}   # seconds
mkdir -p "$OUT" results/task2
log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" | tee -a "$OUT/label_timeline.log"; }

log "deploying Ollama and the teacher prompt"
kubectl apply -f k8s/pipeline/ollama.yaml
kubectl -n pipeline create configmap teacher-prompt --from-file=teacher_prompt.txt=prompts/teacher_prompt.txt \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n pipeline rollout status deploy/ollama --timeout=3600s
kubectl -n pipeline logs deploy/ollama -c pull-teacher > "$OUT/ollama_pull.log" 2>&1 || true
log "Ollama ready: $(kubectl -n pipeline exec deploy/ollama -- ollama list | tail -n +2 | tr -s ' ')"

if [ "${RESUME:-0}" = 1 ]; then
  # continue an interrupted run: put the partial shards back; each worker skips the ids already done
  for f in datasets/teacher/shard-*.jsonl; do
    [ -e "$f" ] && $PY scripts/s3tool.py put "$f" "s3://datasets/teacher/$(basename "$f")"
  done
fi
log "starting the labelling Job (2 workers in parallel)"
kubectl -n pipeline delete job teacher-label --ignore-not-found --wait=true
kubectl apply -f k8s/pipeline/label-job.yaml
for i in $(seq 1 60); do
  running=$(kubectl -n pipeline get pods -l job-name=teacher-label --field-selector=status.phase=Running -o name | wc -l)
  [ "$running" -ge 2 ] && break
  sleep 5
done
{
  echo "# $(date -u +%FT%TZ)  kubectl -n pipeline get pods -l job-name=teacher-label -o wide"
  kubectl -n pipeline get pods -l job-name=teacher-label -o wide
  echo
  echo "# SHARD_INDEX / SHARD_COUNT seen by each Pod"
  for p in $(kubectl -n pipeline get pods -l job-name=teacher-label -o name); do
    echo "$p: $(kubectl -n pipeline exec "$p" -- sh -c 'echo SHARD_INDEX=$SHARD_INDEX SHARD_COUNT=$SHARD_COUNT')"
  done
} | tee "$OUT/workers_running.txt"

start=$(date +%s)
while true; do
  done_=$(kubectl -n pipeline get job teacher-label -o jsonpath='{.status.succeeded}')
  failed=$(kubectl -n pipeline get job teacher-label -o jsonpath='{.status.failed}')
  log "job teacher-label: succeeded=${done_:-0}/2 failed=${failed:-0}; $(kubectl -n pipeline logs -l job-name=teacher-label --tail=1 --prefix 2>/dev/null | tr '\n' ' ' | cut -c1-400)"
  [ "${done_:-0}" -ge 2 ] && break
  if kubectl -n pipeline get job teacher-label -o jsonpath='{.status.conditions[?(@.type=="Failed")].status}' | grep -q True; then
    log "labelling job failed"; exit 1
  fi
  [ $(( $(date +%s) - start )) -gt "$LABEL_TIMEOUT" ] && { log "timeout"; exit 1; }
  sleep 120
done
for p in $(kubectl -n pipeline get pods -l job-name=teacher-label -o name); do
  idx=$(kubectl -n pipeline get "$p" -o jsonpath="{.metadata.annotations['batch\.kubernetes\.io/job-completion-index']}")
  kubectl -n pipeline logs "$p" > "$OUT/worker-shard-$idx.log"
done
kubectl -n pipeline get job teacher-label -o wide > "$OUT/label_job_status.txt"
kubectl -n pipeline describe job teacher-label >> "$OUT/label_job_status.txt"
log "labelling finished"

log "cleaning (clean.py in a Job)"
kubectl -n pipeline delete job clean --ignore-not-found --wait=true
kubectl apply -f k8s/pipeline/clean-job.yaml
kubectl -n pipeline wait --for=condition=complete job/clean --timeout=600s
kubectl -n pipeline logs job/clean | tee "$OUT/clean.log"

log "teacher on the validation texts (same prompt and settings)"
kubectl -n pipeline delete job teacher-eval --ignore-not-found --wait=true
kubectl apply -f k8s/pipeline/teacher-eval-job.yaml
kubectl -n pipeline wait --for=condition=complete job/teacher-eval --timeout=3600s
kubectl -n pipeline logs job/teacher-eval > "$OUT/teacher_eval.log"

log "copying objects out of SeaweedFS"
$PY scripts/s3tool.py get s3://datasets/teacher/ datasets/teacher
$PY scripts/s3tool.py get s3://datasets/v1/ datasets/v1
$PY scripts/s3tool.py get s3://datasets/eval/ results/task2/teacher
$PY scripts/s3tool.py ls | tee "$OUT/s3_listing.txt"

log "checks: coverage of the shards and reproducibility of clean.py"
$PY scripts/check_coverage.py --pool data/commands_pool.jsonl --shards datasets/teacher | tee "$OUT/coverage.txt"
tmp=$(mktemp -d)
$PY worker/clean.py --shards datasets/teacher --out "$tmp" --stats results/task1/clean_stats.json | tee "$OUT/clean_local.log"
{ echo "in cluster: $(cat datasets/v1/train.sha256)"; echo "local rerun: $(cat "$tmp/train.sha256")"; } | tee "$OUT/clean_reproduce.txt"
cmp -s "$tmp/train.sha256" datasets/v1/train.sha256 && echo "MATCH" | tee -a "$OUT/clean_reproduce.txt"

log "scoring the teacher on validation"
$PY scripts/to_predictions.py results/task2/teacher/teacher_validation_raw.jsonl results/task2/teacher_validation_predictions.jsonl
$PY tools/score.py results/task2/teacher_validation_predictions.jsonl data/validation.jsonl \
  --out results/teacher_validation.json | tee results/task2/teacher_score.txt
log "done"
