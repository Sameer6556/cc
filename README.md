# Knowledge distillation and deployment of a command-parsing model on a local cloud

CS3081 Cloud Computing mini project. Student: **Sameer Singh**, roll number **230101096**.

- GitHub repository: https://github.com/Sameer6556/cc
- Model releases (weights, tokenizer, version information, checksums):
  https://github.com/Sameer6556/cc/releases/tag/model-v1 and https://github.com/Sameer6556/cc/releases/tag/model-v2
- CI runs: https://github.com/Sameer6556/cc/actions
- Report: [`report/report.pdf`](report/report.pdf). AI use: [`AI_USE.md`](AI_USE.md).

A teacher model (phi3.5, 3.8 B parameters, served by Ollama) labels 3,000 voice commands with a four-key
JSON frame. A 70 M-parameter student (EleutherAI/pythia-70m) is fine-tuned on the teacher's replies
(sequence-level knowledge distillation). The student is then served by a FastAPI service on a single-node
k3d Kubernetes cluster, with SeaweedFS object storage, a Traefik Ingress, probes, an HPA, rolling updates
and CI.

```
            make up                                         namespace app
  +---------------------------+   Ingress /parse   +------------------------------------+
  | k3d cluster (cluster/     |  --------------->  | Service parser -> Deployment parser |
  |  k3d.yaml), Traefik :8080 |                    | (1-2 Pods, HPA 70 % CPU)            |
  +---------------------------+                    +------------------+-----------------+
            |                                                         | model download at start-up
  namespace pipeline                         namespace data           v (read-only credentials)
  +---------------------------+    S3     +------------------------------------------------+
  | Ollama phi3.5, 2 workers  | <-------> | SeaweedFS: buckets datasets/ and models/v1,v2/ |
  | (Indexed Job), clean.py   |           +------------------------------------------------+
  +---------------------------+
```

## Repository layout

| Path | What |
|---|---|
| `cluster/k3d.yaml` | the cluster definition (1 server node, Traefik on host port 8080, S3 NodePort on 127.0.0.1:30333) |
| `prompts/teacher_prompt.txt` | the teacher prompt (`{command}` is replaced by each command) |
| `worker/` | labelling worker (`SHARD_INDEX`/`SHARD_COUNT`), `clean.py`, Dockerfile |
| `training/` | `config.yaml`, `train.py` (`make train`), `predict.py`, `loss.csv` (v1), `loss_v2.csv` (v2) |
| `service/` | FastAPI inference service, shared model code (`parser_core.py`), Dockerfile, pinned lock file |
| `k8s/data`, `k8s/pipeline`, `k8s/app` | Kubernetes manifests per namespace |
| `network/` | `subnets.md` (Task 5 table and working), `nacl.json`, test packets |
| `datasets/` | raw teacher shards and the cleaned `v1/train.jsonl` + `train.sha256` (copied out of object storage) |
| `models/v1`, `models/v2` | `model.sha256` only; the weights live in object storage and in the GitHub Releases |
| `scripts/` | secrets, S3 tool, labelling orchestration, experiments, CI helpers |
| `tests/` | unit tests (`make test`) |
| `tools/`, `data/` | the student kit, unmodified |
| `results/` | every log, score report, Locust output and command output used in the report |
| `.github/workflows/` | `ci.yml` (lint, tests, evaluation, quality gate, gitleaks) and the experiment workflows |

## Prerequisites

Linux or macOS with Docker (24+), [k3d](https://k3d.io) 5.7+, kubectl 1.30+, GNU make, curl and Python
3.11 to 3.13. About 8 GB of free disk and 6 GB of RAM. Nothing else is needed: Python packages are
installed into local virtual environments (`.venv*`) by the Makefile.

## Build and deploy (from a fresh clone, three commands)

```bash
git clone https://github.com/Sameer6556/cc.git
```

```bash
cd cc
```

```bash
make up
```

`make up` creates the cluster from `cluster/k3d.yaml` and generates S3 credentials into Kubernetes
Secrets (they are never stored in Git). It deploys SeaweedFS in `data`, creates the buckets `datasets`
and `models`, and uploads `commands_pool.jsonl`. It downloads the model Releases `model-v1` and
`model-v2`, verifies them against `model.sha256` and uploads them to `s3://models/v1/` and
`s3://models/v2/`. Finally it builds the service image (no weights inside), imports it into the
cluster, deploys the Deployment, Service, Ingress and HPA in `app`, and sends one request through the
Ingress.

Try it:

```bash
curl -i -X POST http://localhost:8080/parse -H 'Content-Type: application/json' -d '{"text": "set an alarm for seven thirty am tomorrow"}'
```

Behind a TLS-intercepting proxy, pass its CA to the image builds:
`make up DOCKER_BUILD_FLAGS="--secret id=extra_ca,src=/path/to/proxy-ca.pem"`.

## Test

```bash
make lint test
```

Train the student on the first 50 records only, as a quick check:

```bash
make train SUBSET=50
```

Full training and evaluation (`make train`, `make train MODEL_VERSION=v2`, `make eval`,
`make eval-untrained`) read every setting from `training/config.yaml`.

The standard load test (Task 7), run from the repository root:

```bash
make loadtest
```

This is exactly `locust -f tools/locustfile.py --headless --users 4 --spawn-rate 4 --run-time 2m --host http://localhost:8080 --csv results/loadtest`.

The other experiments (container limits, cold start, HPA, rolling update and rollback, recovery, load
balancing) run against a cluster created by `make up`:

```bash
bash scripts/experiments/run_all.sh
```

Teacher labelling (Task 1) takes several hours on a CPU. It deploys Ollama and two parallel workers, then
runs `clean.py` and the teacher's validation run:

```bash
make up && make label
```

## Shut down

```bash
make down
```

This deletes the k3d cluster and everything in it. `make clean` also removes the local virtual
environments and training outputs.

## Where the evidence is

| Task | Evidence |
|---|---|
| 1 | `results/task1/` (worker logs, two workers running, coverage check, clean counts, checksum reproduction, S3 listing), `datasets/` |
| 2 | `training/config.yaml`, `training/loss.csv`, `training/loss_v2.csv`, `results/task2/`, `results/teacher_validation.json`, `models/v*/model.sha256` |
| 3 | `results/task3/` (image size, no weights, endpoints, 50 requests at 1 CPU / 1 GiB, peak memory, fault injection) |
| 4 | `results/task4/` (basics, cold start, HPA, rolling update and rollback, recovery, load balancing) |
| 5 | `network/subnets.md`, `network/nacl.json`, `results/network/` |
| 6 | `.github/workflows/ci.yml`, `results/task6/`, `AI_USE.md` |
| 7 | `results/loadtest_*`, `results/task7/` (latency, throughput, errors, `kubectl top pods`, cost, SLO) |
