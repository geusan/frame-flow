.PHONY: setup up down ps logs dev-storage dev-web dev-api seed-skills seed-assets test build check tf-init tf-fmt tf-validate tf-plan tf-apply tf-destroy

ifneq (,$(wildcard .env))
include .env
export
endif

API_PORT ?= 8000
MINIO_PORT ?= 9000
IMPORT_ROOT ?= /imports
TF_DIR ?= infra/terraform
TF_ENV ?= dev
TF_VARS ?= environments/$(TF_ENV).tfvars

setup:
	python3 -m venv .venv
	.venv/bin/pip install -r apps/api/requirements.txt
	npm install

up:
	docker compose config -q
	docker compose up -d --build

down:
	docker compose down

ps:
	docker compose ps

logs:
	docker compose logs -f --tail=200

dev-web:
	npm run dev

dev-storage:
	MINIO_PORT=$(MINIO_PORT) docker compose up -d minio

dev-api: dev-storage
	cd apps/api && ../../.venv/bin/alembic upgrade head
	cd apps/api && API_PUBLIC_BASE_URL=$${API_PUBLIC_BASE_URL:-http://localhost:$(API_PORT)} STORAGE_ENDPOINT=$${STORAGE_ENDPOINT:-http://localhost:$(MINIO_PORT)} STORAGE_PUBLIC_ENDPOINT=$${STORAGE_PUBLIC_ENDPOINT:-http://localhost:$(MINIO_PORT)} ../../.venv/bin/uvicorn app.main:app --reload --port $(API_PORT)

seed-skills:
	cd apps/api && ../../.venv/bin/python -m app.seed skills --root "$(IMPORT_ROOT)"

seed-assets:
	cd apps/api && ../../.venv/bin/python -m app.seed assets --root "$(IMPORT_ROOT)"

test:
	cd apps/api && ../../.venv/bin/pytest -q
	cd apps/worker && ../../.venv/bin/pytest -q

build:
	npm run build

check:
	npm run lint
	npm run typecheck
	npm run ui:check
	$(MAKE) test
	$(MAKE) build

tf-init:
	terraform -chdir=$(TF_DIR) init

tf-fmt:
	terraform -chdir=$(TF_DIR) fmt -check -recursive

tf-validate: tf-init
	terraform -chdir=$(TF_DIR) validate

tf-plan: tf-init
	test -f "$(TF_DIR)/$(TF_VARS)" || (echo "Copy $(TF_DIR)/environments/$(TF_ENV).tfvars.example to $(TF_DIR)/$(TF_VARS)"; exit 1)
	terraform -chdir=$(TF_DIR) plan -var-file="$(TF_VARS)" -out="$(TF_ENV).tfplan"

tf-apply:
	test -f "$(TF_DIR)/$(TF_ENV).tfplan" || (echo "Run make tf-plan TF_ENV=$(TF_ENV) first"; exit 1)
	terraform -chdir=$(TF_DIR) apply "$(TF_ENV).tfplan"

tf-destroy: tf-init
	test "$(CONFIRM_DESTROY)" = "$(TF_ENV)" || (echo "Set CONFIRM_DESTROY=$(TF_ENV) to destroy this environment"; exit 1)
	terraform -chdir=$(TF_DIR) destroy -var-file="$(TF_VARS)"
