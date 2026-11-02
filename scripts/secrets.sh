#!/usr/bin/env bash
# Generate S3 credentials for this cluster and store them ONLY in Kubernetes Secrets and in
# .secrets/s3.env (git-ignored). Nothing secret is ever written to the repository.
#
#   admin identity  : full access, used by `make up` (seeding) and the labelling pipeline
#   reader identity : read/list on the "models" bucket only, used by the inference service
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p .secrets
chmod 700 .secrets

if [[ ! -f .secrets/s3.env ]]; then
  gen() { head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n' | cut -c1-"$1"; }
  {
    echo "S3_ADMIN_ACCESS_KEY=$(gen 20)"
    echo "S3_ADMIN_SECRET_KEY=$(gen 40)"
    echo "S3_READER_ACCESS_KEY=$(gen 20)"
    echo "S3_READER_SECRET_KEY=$(gen 40)"
  } > .secrets/s3.env
  chmod 600 .secrets/s3.env
fi
# shellcheck disable=SC1091
source .secrets/s3.env

cat > .secrets/s3.json <<EOF
{
  "identities": [
    {"name": "admin",
     "credentials": [{"accessKey": "${S3_ADMIN_ACCESS_KEY}", "secretKey": "${S3_ADMIN_SECRET_KEY}"}],
     "actions": ["Admin", "Read", "List", "Tagging", "Write"]},
    {"name": "model-reader",
     "credentials": [{"accessKey": "${S3_READER_ACCESS_KEY}", "secretKey": "${S3_READER_SECRET_KEY}"}],
     "actions": ["Read:models", "List:models"]}
  ]
}
EOF
chmod 600 .secrets/s3.json

for ns in data pipeline app; do
  kubectl create namespace "$ns" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
done
kubectl -n data create secret generic seaweedfs-s3-config --from-file=s3.json=.secrets/s3.json \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n pipeline create secret generic s3-credentials \
  --from-literal=AWS_ACCESS_KEY_ID="${S3_ADMIN_ACCESS_KEY}" \
  --from-literal=AWS_SECRET_ACCESS_KEY="${S3_ADMIN_SECRET_KEY}" \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n app create secret generic s3-credentials \
  --from-literal=AWS_ACCESS_KEY_ID="${S3_READER_ACCESS_KEY}" \
  --from-literal=AWS_SECRET_ACCESS_KEY="${S3_READER_SECRET_KEY}" \
  --dry-run=client -o yaml | kubectl apply -f -
echo "secrets ready (values kept in .secrets/, which git ignores)"
