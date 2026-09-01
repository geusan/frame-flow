.PHONY: setup up down ps logs migrate-runtime-permissions dev-storage dev-web dev-api seed-skills seed-assets test build check lock-python security-tools security-secrets security-node security-python security-deps security-sbom security-images security-all tf-init tf-fmt tf-validate tf-plan tf-apply tf-destroy

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
SECURITY_VENV ?= .security-venv
SECURITY_ARTIFACT_DIR ?= artifacts/security
GITLEAKS_IMAGE ?= ghcr.io/gitleaks/gitleaks:v8.30.1
SYFT_IMAGE ?= anchore/syft:v1.51.1
TRIVY_IMAGE ?= aquasec/trivy:0.74.0
PIP_AUDIT_VERSION ?= 2.10.1
PIP_TOOLS_VERSION ?= 7.6.1

setup:
	python3 -m venv .venv
	.venv/bin/pip install --require-hashes -r apps/api/requirements.lock.txt
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

migrate-runtime-permissions:
	docker compose build api
	docker compose run --rm --no-deps --user 0 api chown -R 1000:1000 /home/frameflow/.cache

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

security-tools:
	@test -x "$(SECURITY_VENV)/bin/python" || python3 -m venv "$(SECURITY_VENV)"
	@"$(SECURITY_VENV)/bin/pip" install --quiet "pip-audit==$(PIP_AUDIT_VERSION)" "pip-tools==$(PIP_TOOLS_VERSION)"

lock-python: security-tools
	"$(SECURITY_VENV)/bin/pip-compile" --quiet --generate-hashes --no-annotate --no-header --strip-extras --resolver=backtracking --output-file apps/api/requirements.lock.txt apps/api/requirements.txt

security-secrets:
	docker run --rm -v "$(CURDIR):/repo:ro" "$(GITLEAKS_IMAGE)" git --config=/repo/.gitleaks.toml --gitleaks-ignore-path=/repo/.gitleaksignore --redact --no-banner /repo

security-node:
	npm audit --omit=dev --audit-level=high

security-python: security-tools
	"$(SECURITY_VENV)/bin/python" -m unittest discover -s scripts/security -p 'test_*.py'
	"$(SECURITY_VENV)/bin/python" scripts/security/python_audit.py

security-deps: security-node security-python

security-sbom:
	mkdir -p "$(SECURITY_ARTIFACT_DIR)"
	docker run --rm -v "$(CURDIR):/repo:ro" -v "$(CURDIR)/$(SECURITY_ARTIFACT_DIR):/output" "$(SYFT_IMAGE)" scan dir:/repo --config /repo/.syft.yaml --output spdx-json=/output/frame-flow-source.spdx.json --output cyclonedx-json=/output/frame-flow-source.cdx.json
	python3 scripts/security/check_sbom_licenses.py "$(SECURITY_ARTIFACT_DIR)/frame-flow-source.spdx.json"

security-images:
	mkdir -p "$(SECURITY_ARTIFACT_DIR)/trivy-cache" "$(SECURITY_ARTIFACT_DIR)/trivy-tmp"
	docker build -f apps/api/Dockerfile -t frame-flow-api:security .
	docker build -f apps/web/Dockerfile -t frame-flow-web:security .
	docker run --rm -v /var/run/docker.sock:/var/run/docker.sock -v "$(CURDIR)/$(SECURITY_ARTIFACT_DIR)/trivy-cache:/root/.cache/trivy" -v "$(CURDIR)/$(SECURITY_ARTIFACT_DIR)/trivy-tmp:/tmp" "$(TRIVY_IMAGE)" image --scanners vuln --ignore-unfixed --severity HIGH,CRITICAL --exit-code 1 frame-flow-api:security
	docker run --rm -v /var/run/docker.sock:/var/run/docker.sock -v "$(CURDIR)/$(SECURITY_ARTIFACT_DIR)/trivy-cache:/root/.cache/trivy" -v "$(CURDIR)/$(SECURITY_ARTIFACT_DIR)/trivy-tmp:/tmp" "$(TRIVY_IMAGE)" image --scanners vuln --ignore-unfixed --severity HIGH,CRITICAL --exit-code 1 frame-flow-web:security

security-all: security-secrets security-deps security-sbom security-images

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
