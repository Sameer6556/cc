#!/usr/bin/env bash
# Task 4.7 (and the readiness criterion of 4.2): delete ALL parser Pods three times. For each run,
# record (a) a 0.5 s timeline of the Service's ready endpoints while the new Pods load the model,
# (b) each new Pod's logs (model download from object storage), (c) Pod creation -> Ready time.
source "$(dirname "$0")/lib.sh"
OUT=$RESULTS/task4/coldstart
RUNS=${RUNS:-3}
mkdir -p "$OUT"
LOG=$OUT/coldstart.log
: > "$LOG"
for run in $(seq 1 "$RUNS"); do
  old=$(kubectl -n app get pods -l app=parser -o jsonpath='{.items[*].metadata.name}')
  log "run $run: deleting all parser pods: $old"
  kubectl -n app delete pods -l app=parser --wait=false >/dev/null
  t0=$(date +%s)
  : > "$OUT/run${run}_endpoints.log"
  # 0.5 s timeline: ready endpoints behind the Service and the readiness of every Pod
  while [ $(( $(date +%s) - t0 )) -lt 240 ]; do
    pods=$(kubectl -n app get pods -l app=parser --no-headers \
      -o custom-columns=N:.metadata.name,READY:.status.containerStatuses[0].ready,PHASE:.status.phase 2>/dev/null | tr -s ' ' | tr '\n' ';')
    eps=$(ready_endpoints || echo '?')
    echo "$(ts) ready_endpoints=$eps pods=[$pods]" >> "$OUT/run${run}_endpoints.log"
    new_ready=0; new_total=0
    for p in $(kubectl -n app get pods -l app=parser -o jsonpath='{.items[*].metadata.name}'); do
      case " $old " in *" $p "*) continue ;; esac
      new_total=$((new_total + 1))
      if [ "$(kubectl -n app get pod "$p" -o jsonpath='{.status.containerStatuses[0].ready}' 2>/dev/null)" = true ]; then
        new_ready=$((new_ready + 1))
      fi
    done
    still_old=0
    for p in $old; do if kubectl -n app get pod "$p" >/dev/null 2>&1; then still_old=$((still_old + 1)); fi; done
    if [ "$new_total" -gt 0 ] && [ "$new_ready" = "$new_total" ] && [ "$still_old" = 0 ]; then break; fi
    sleep 0.5
  done
  for p in $(kubectl -n app get pods -l app=parser -o jsonpath='{.items[*].metadata.name}'); do
    case " $old " in *" $p "*) continue ;; esac
    kubectl -n app logs "$p" > "$OUT/run${run}_${p}.log" 2>&1
    kubectl -n app get pod "$p" -o json > "$OUT/run${run}_${p}.json"
  done
  log "run $run done: $(grep -c . "$OUT/run${run}_endpoints.log") samples"
  sleep 5
done
"$PY" - "$OUT" "$RUNS" <<'EOF' | tee "$OUT/summary.txt"
import glob, json, re, statistics, sys
from datetime import datetime
out, runs = sys.argv[1], int(sys.argv[2])
def t(s): return datetime.strptime(s, '%Y-%m-%dT%H:%M:%SZ')
per_run = []
for run in range(1, runs + 1):
    pods = []
    for f in sorted(glob.glob(f'{out}/run{run}_*.json')):
        p = json.load(open(f))
        created = t(p['metadata']['creationTimestamp'])
        ready = next(c for c in p['status']['conditions'] if c['type'] == 'Ready')
        secs = (t(ready['lastTransitionTime']) - created).total_seconds()
        log = open(f[:-5] + '.log').read()
        dl = re.search(r'downloaded (\d+) objects \(([\d.]+) MB\) in ([\d.]+)s', log)
        ld = re.search(r'model loaded in ([\d.]+)s', log)
        pods.append({'pod': p['metadata']['name'], 'created': p['metadata']['creationTimestamp'],
                     'ready': ready['lastTransitionTime'], 'creation_to_ready_s': secs,
                     'download_s': float(dl.group(3)) if dl else None, 'download_mb': float(dl.group(2)) if dl else None,
                     'load_s': float(ld.group(1)) if ld else None})
    zero = [l for l in open(f'{out}/run{run}_endpoints.log') if 'ready_endpoints=0 ' in l]
    per_run.append({'run': run, 'pods': pods, 'cold_start_s': max(p['creation_to_ready_s'] for p in pods),
                    'samples_with_zero_ready_endpoints': len(zero)})
    print(f"run {run}: " + ', '.join(f"{p['pod']} {p['creation_to_ready_s']:.0f}s (download {p['download_s']}s, load {p['load_s']}s)" for p in pods)
          + f"; samples with 0 ready endpoints: {len(zero)}")
med = statistics.median(r['cold_start_s'] for r in per_run)
print(f'median cold start (Pod creation -> Ready, slowest new Pod per run) over {runs} runs: {med:.1f} s')
json.dump({'runs': per_run, 'median_cold_start_s': med}, open(f'{out}/summary.json', 'w'), indent=2)
EOF
