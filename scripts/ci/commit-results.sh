#!/usr/bin/env bash
# Commit experiment evidence produced on a CI runner back to the branch that ran the workflow.
#   scripts/ci/commit-results.sh "message" path [path ...]
set -euo pipefail
msg=$1; shift
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git add -A -- "$@"
if git diff --cached --quiet; then echo "nothing to commit"; exit 0; fi
git commit -q -m "$msg" -m "Produced by workflow run ${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}/actions/runs/${GITHUB_RUN_ID}"
for i in 1 2 3 4 5; do
  git pull -q --rebase origin "${GITHUB_REF_NAME}" && git push -q origin "HEAD:${GITHUB_REF_NAME}" && exit 0
  sleep $((i * 5))
done
echo "push failed" >&2; exit 1
