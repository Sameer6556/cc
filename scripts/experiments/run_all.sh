#!/usr/bin/env bash
# Run every Task 3, 4 and 7 experiment against a cluster created with `make up`.
set -euo pipefail
cd "$(dirname "$0")/../.."
make venv venv-locust >/dev/null
D=scripts/experiments
bash $D/task4_basics.sh
bash $D/task3_container.sh
bash $D/task4_coldstart.sh
bash $D/task4_hpa.sh
bash $D/task4_rolling.sh
bash $D/task4_recovery.sh
bash $D/task4_loadbalance.sh
bash $D/task7_loadtest.sh
