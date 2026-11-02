# Knowledge distillation + local cloud deployment. Run `make help` for the targets.
#
# From a fresh clone (Task 6):   git clone <repo> && cd cc && make up
# Tear everything down:          make down
SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

CLUSTER       ?= cc
REPO          ?= Sameer6556/cc
IMAGE         ?= parser-service:0.1.0
WORKER_IMAGE  ?= teacher-worker:0.1.0
PYTHON        ?= python3
INGRESS       ?= http://localhost:8080
MODEL_VERSION ?= v1
SUBSET        ?=
RUN_TIME      ?= 2m
# Extra flags for docker build, e.g. DOCKER_BUILD_FLAGS="--secret id=extra_ca,src=ca.pem" behind a TLS proxy
DOCKER_BUILD_FLAGS ?=

VENV        := .venv
TRAIN_VENV  := .venv-train
LOCUST_VENV := .venv-locust
TORCH_INDEX := https://download.pytorch.org/whl/cpu

.PHONY: help up down cluster secrets storage seed seed-data seed-models image deploy smoke status \
        worker-image label train eval eval-untrained test lint loadtest venv venv-train venv-locust clean

help: ## list the targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-16s %s\n", $$1, $$2}'

# ---------------------------------------------------------------- whole system (Task 6)
up: venv cluster secrets storage seed image deploy smoke ## build and deploy the whole system (cluster, storage, models, service)
	@echo "system is up: curl -X POST $(INGRESS)/parse -H 'Content-Type: application/json' -d '{\"text\": \"what is the weather in paris\"}'"

down: ## delete the cluster and everything in it
	k3d cluster delete $(CLUSTER)

cluster: ## create the k3d cluster from cluster/k3d.yaml (idempotent)
	@k3d cluster get $(CLUSTER) >/dev/null 2>&1 || k3d cluster create --config cluster/k3d.yaml
	kubectl config use-context k3d-$(CLUSTER)
	kubectl wait --for=condition=Ready node --all --timeout=180s

secrets: ## generate S3 credentials into Kubernetes Secrets (never into Git)
	./scripts/secrets.sh

storage: ## deploy SeaweedFS in the data namespace
	kubectl apply -f k8s/data/seaweedfs.yaml
	kubectl -n data rollout status deploy/seaweedfs --timeout=300s
	$(VENV)/bin/python scripts/wait_s3.py

seed: seed-data seed-models ## create buckets, upload the dataset and the released models (v1, v2)

seed-data: venv ## create the buckets datasets and models, upload commands_pool.jsonl
	$(VENV)/bin/python scripts/s3tool.py buckets
	$(VENV)/bin/python scripts/s3tool.py seed-data

seed-models: venv ## download the model Releases (v1, v2), verify checksums, upload to s3://models/
	$(VENV)/bin/python scripts/s3tool.py release-model v1 --repo $(REPO)
	$(VENV)/bin/python scripts/s3tool.py release-model v2 --repo $(REPO)

image: ## build the service image (no weights inside) and import it into the cluster
	docker build $(DOCKER_BUILD_FLAGS) -f service/Dockerfile -t $(IMAGE) .
	k3d image import $(IMAGE) -c $(CLUSTER)

deploy: ## deploy Deployment, Service, Ingress and HPA in the app namespace
	kubectl apply -f k8s/app/parser.yaml
	kubectl -n app rollout status deploy/parser --timeout=600s

smoke: ## one request through the Ingress
	@for i in $$(seq 1 30); do curl -sf -o /dev/null -X POST $(INGRESS)/parse -H 'Content-Type: application/json' -d '{"text":"ping"}' && break; [ $$? -eq 22 ] && break; sleep 2; done
	curl -sS -i -X POST $(INGRESS)/parse -H 'Content-Type: application/json' -d '{"text":"set an alarm for seven thirty am tomorrow"}'; echo

status: ## show what is running
	kubectl get nodes -o wide
	kubectl get all,ingress,hpa,pvc -n data
	kubectl get all,ingress,hpa -n app

# ---------------------------------------------------------------- teacher labelling (Task 1)
worker-image: ## build the labelling worker image and import it into the cluster
	docker build $(DOCKER_BUILD_FLAGS) -f worker/Dockerfile -t $(WORKER_IMAGE) .
	k3d image import $(WORKER_IMAGE) -c $(CLUSTER)

label: venv worker-image ## run Ollama + two parallel workers in the pipeline namespace, then clean.py (hours on a CPU)
	./scripts/label.sh

# ---------------------------------------------------------------- training and evaluation (Task 2)
train: venv-train ## fine-tune Pythia-70M from training/config.yaml (SUBSET=50 for a quick check, MODEL_VERSION=v2)
	$(TRAIN_VENV)/bin/python training/train.py --config training/config.yaml --version $(MODEL_VERSION) $(if $(SUBSET),--subset $(SUBSET),)

eval: venv-train ## score a trained model on validation.jsonl (MODEL_VERSION=v1|v2)
	mkdir -p results/eval
	$(TRAIN_VENV)/bin/python training/predict.py --model artifacts/models/$(MODEL_VERSION) \
	  --out results/eval/student_$(MODEL_VERSION)_validation_predictions.jsonl
	$(PYTHON) tools/score.py results/eval/student_$(MODEL_VERSION)_validation_predictions.jsonl data/validation.jsonl \
	  --out results/eval/student_$(MODEL_VERSION)_validation.json

eval-untrained: venv-train ## score the original, untrained Pythia-70M with the same prompt and decoding
	mkdir -p results/eval
	$(TRAIN_VENV)/bin/python training/predict.py --model EleutherAI/pythia-70m \
	  --out results/eval/untrained_validation_predictions.jsonl
	$(PYTHON) tools/score.py results/eval/untrained_validation_predictions.jsonl data/validation.jsonl \
	  --out results/eval/untrained_validation.json

# ---------------------------------------------------------------- quality (Task 6)
test: venv ## unit tests
	$(VENV)/bin/pytest -q tests

lint: venv ## static checks
	$(VENV)/bin/ruff check .

loadtest: venv-locust ## the standard load test through the Ingress (RUN_TIME=2m)
	mkdir -p results
	$(LOCUST_VENV)/bin/locust -f tools/locustfile.py --headless --users 4 --spawn-rate 4 \
	  --run-time $(RUN_TIME) --host $(INGRESS) --csv results/loadtest

# ---------------------------------------------------------------- virtual environments
venv: $(VENV)/.ok
$(VENV)/.ok: requirements-dev.txt
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install -q -r requirements-dev.txt
	touch $@

venv-train: $(TRAIN_VENV)/.ok
$(TRAIN_VENV)/.ok: service/requirements.txt training/requirements.txt
	$(PYTHON) -m venv $(TRAIN_VENV)
	$(TRAIN_VENV)/bin/pip install -q --no-deps --index-url $(TORCH_INDEX) torch==2.14.1
	$(TRAIN_VENV)/bin/pip install -q --no-deps -r training/requirements.txt
	touch $@

venv-locust: $(LOCUST_VENV)/.ok
$(LOCUST_VENV)/.ok: requirements-loadtest.txt
	$(PYTHON) -m venv $(LOCUST_VENV)
	$(LOCUST_VENV)/bin/pip install -q -r requirements-loadtest.txt
	touch $@

clean: ## remove local virtual environments and training outputs (not the cluster)
	rm -rf $(VENV) $(TRAIN_VENV) $(LOCUST_VENV) artifacts
