#!/usr/bin/env bash
# Task 4.1-4.4: the objects in the app namespace, requests/limits, probes, HPA, /parse through the Ingress.
source "$(dirname "$0")/lib.sh"
OUT=$RESULTS/task4/basics
mkdir -p "$OUT"
{
  echo "# $(ts) kubectl get nodes -o wide"; kubectl get nodes -o wide; echo
  echo "# kubectl -n app get deploy,rs,pods,svc,ingress,hpa,endpointslices -o wide"
  kubectl -n app get deploy,rs,pods,svc,ingress,hpa,endpointslices -o wide; echo
  echo "# requests, limits and probes of the parser container"
  kubectl -n app get deploy parser -o jsonpath='{range .spec.template.spec.containers[*]}resources: {.resources}{"\n"}readinessProbe: {.readinessProbe}{"\n"}livenessProbe: {.livenessProbe}{"\n"}{end}' ; echo
  kubectl -n app get deploy parser -o jsonpath='{.spec.strategy}'; echo; echo
  echo "# kubectl -n app describe hpa parser"; kubectl -n app describe hpa parser
} > "$OUT/resources.txt" 2>&1
kubectl -n app get deploy parser -o yaml > "$OUT/deployment.yaml"
{
  echo "# $(ts) POST /parse through the Traefik Ingress ($INGRESS)"
  curl -sS -i -X POST "$INGRESS/parse" -H 'Content-Type: application/json' -d '{"text": "what is the weather in london"}'
  echo; echo
  echo "# the Ingress only routes /parse: GET $INGRESS/readyz"
  curl -sS -i "$INGRESS/readyz"; echo
} > "$OUT/ingress_curl.txt" 2>&1
log "wrote $OUT"
