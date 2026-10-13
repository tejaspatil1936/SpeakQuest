# SpeakQuest — developer and operator commands.
#
#   make setup        install Python (uv) and web (npm) dependencies
#   make models       download the Vosk model and Piper voices
#   make dataset      synthesise the labelled evaluation dataset
#   make local        seed + run the API, storage and workflow on :8787
#   make web          run the web app on :5173 against the local API
#   make check        every lint, type check and test
#
#   make up           first deploy: ECR → image → everything → seed (system design §8.4)
#   make deploy       rebuild + push the worker image and roll the Lambda to it
#   make seed         upload and pre-analyse the reference takes
#   make down         terraform destroy, then scripts/verify-zero.sh
#
# AWS credentials come from your shell or ./.env (scripts/with-aws-env.sh).
# Terraform asks before applying/destroying unless AUTO_APPROVE=1.

SHELL := bash
.SHELLFLAGS := -euo pipefail -c
.DEFAULT_GOAL := help

PY        := .venv/bin/python
UV_EXTRAS := --extra worker --extra aws --extra dev --extra asr --extra fixtures
AWS       := scripts/with-aws-env.sh
TF        := $(AWS) terraform -chdir=infra
TF_FLAGS  := $(if $(filter 1,$(AUTO_APPROVE)),-auto-approve,)
DIGEST_FILE := infra/.worker-digest
WORKER_TAG ?= $(shell git rev-parse --short HEAD 2>/dev/null || echo dev)
API_PORT  ?= 8787
export SPEAKQUEST_MODEL_DIR ?= $(CURDIR)/.models

.PHONY: help
help: ## list targets
	@grep -hE '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*## "}{printf "  %-16s %s\n",$$1,$$2}'

# ------------------------------------------------------------------ setup

.PHONY: setup setup-py setup-web models dataset
setup: setup-py setup-web ## install all dependencies

setup-py: ## Python 3.12 venv from uv.lock
	uv sync $(UV_EXTRAS)

setup-web: ## web dependencies from package-lock.json
	npm --prefix web ci

models: ## download Vosk + Piper models into .models/
	scripts/download-models.sh

dataset: ## synthesise the labelled clips (data/audio, data/annotations)
	$(PY) -m speakquest_eval.cli generate

# ------------------------------------------------------------------ quality

.PHONY: check lint typecheck test test-fast web-check contracts contracts-check fixtures eval
check: lint typecheck contracts-check test web-check tf-check ## everything CI runs

lint: ## ruff (Python) + eslint (web)
	.venv/bin/ruff check .
	.venv/bin/ruff format --check .
	npm --prefix web run lint

typecheck: ## mypy + tsc
	.venv/bin/mypy
	npm --prefix web run typecheck

test: ## all Python tests (slow/asr ones skip if models or data are missing)
	.venv/bin/pytest

test-fast: ## Python tests without audio processing
	.venv/bin/pytest -m "not slow"

web-check: ## web unit tests + production build
	npm --prefix web test
	npm --prefix web run build

contracts: ## regenerate contracts/schema.json from the Pydantic models
	$(PY) scripts/export_schemas.py

contracts-check:
	$(PY) scripts/export_schemas.py --check

fixtures: ## regenerate the web demo fixtures from real pipeline runs
	$(PY) scripts/make_demo_fixtures.py

eval: ## evaluate detection on dev and held-out splits → eval/reports/
	$(PY) -m speakquest_eval.cli run --split dev
	$(PY) -m speakquest_eval.cli run --split heldout

# ------------------------------------------------------------------ local runtime

.PHONY: local local-seed web smoke-worker
local-seed: ## pre-analyse references into .local/
	$(PY) -m speakquest_api.local.server seed

local: ## run the API + storage + workflow locally (Bedrock coaching if AWS creds exist)
	@[ -f .local/speakquest.sqlite ] || $(MAKE) local-seed
	$(AWS) $(PY) -m speakquest_api.local.server serve --port $(API_PORT)

web: ## Vite dev server against the local API
	VITE_API_URL=http://localhost:$(API_PORT) npm --prefix web run dev

smoke-worker: build-worker ## run the worker image as a Lambda against moto
	$(PY) scripts/smoke_worker_image.py speakquest-worker:local

# ------------------------------------------------------------------ build

.PHONY: build-lambda build-worker
build-lambda: ## zip bundle for the api/explain/persist Lambdas
	scripts/build-lambda.sh

build-worker: ## worker container image (speakquest-worker:local)
	scripts/build-worker.sh speakquest-worker:local

# ------------------------------------------------------------------ AWS

.PHONY: tf-init tf-check plan up deploy seed down verify-zero push-worker
tf-init:
	$(TF) init -input=false

tf-check: ## terraform fmt + validate (no AWS calls)
	terraform -chdir=infra fmt -check -recursive
	terraform -chdir=infra init -backend=false -input=false >/dev/null
	terraform -chdir=infra validate

plan: build-lambda tf-init ## terraform plan
	$(TF) plan -input=false $(if $(wildcard $(DIGEST_FILE)),-var worker_image_digest=$$(cat $(DIGEST_FILE)),)

push-worker: build-worker
	@repo=$$($(TF) output -raw ecr_repository_url); \
	region=$$($(TF) output -raw region); \
	$(AWS) aws ecr get-login-password --region $$region | docker login --username AWS --password-stdin $${repo%%/*}; \
	docker tag speakquest-worker:local $$repo:$(WORKER_TAG); \
	docker push $$repo:$(WORKER_TAG) | tail -1; \
	digest=$$(docker inspect --format '{{index .RepoDigests 0}}' $$repo:$(WORKER_TAG) | sed 's/.*@//'); \
	echo "$$digest" > $(DIGEST_FILE); echo "worker image $$digest"

up: build-lambda tf-init ## first deploy: registry → image → all → seed
	$(TF) apply -input=false $(TF_FLAGS) -target=module.registry
	$(MAKE) push-worker
	$(TF) apply -input=false $(TF_FLAGS) -var worker_image_digest=$$(cat $(DIGEST_FILE))
	$(MAKE) seed
	@$(TF) output

deploy: push-worker ## roll the worker Lambda to a freshly built image
	$(TF) apply -input=false $(TF_FLAGS) -target=module.worker -var worker_image_digest=$$(cat $(DIGEST_FILE))

seed: ## upload + pre-analyse reference takes (Amazon Transcribe timings)
	$(AWS) $(PY) -m speakquest_api.cloud seed --aligner $${SEED_ALIGNER:-transcribe}

down: ## destroy everything, then verify nothing billable is left
	$(TF) destroy -input=false $(TF_FLAGS) $(if $(wildcard $(DIGEST_FILE)),-var worker_image_digest=$$(cat $(DIGEST_FILE)),)
	rm -f $(DIGEST_FILE)
	$(MAKE) verify-zero

verify-zero: ## list anything SpeakQuest left behind in the account
	$(AWS) scripts/verify-zero.sh
