.PHONY: setup dev-storage dev-web dev-api test build check

API_PORT ?= 8000
MINIO_PORT ?= 9000

setup:
	python3 -m venv .venv
	.venv/bin/pip install -r apps/api/requirements.txt
	npm install

dev-web:
	npm run dev

dev-storage:
	MINIO_PORT=$(MINIO_PORT) docker compose up -d minio

dev-api: dev-storage
	cd apps/api && API_PUBLIC_BASE_URL=$${API_PUBLIC_BASE_URL:-http://localhost:$(API_PORT)} STORAGE_ENDPOINT=$${STORAGE_ENDPOINT:-http://localhost:$(MINIO_PORT)} STORAGE_PUBLIC_ENDPOINT=$${STORAGE_PUBLIC_ENDPOINT:-http://localhost:$(MINIO_PORT)} ../../.venv/bin/uvicorn app.main:app --reload --port $(API_PORT)

test:
	cd apps/api && ../../.venv/bin/pytest -q
	cd apps/worker && ../../.venv/bin/pytest -q

build:
	npm run build

check:
	npm run lint
	npm run typecheck
	$(MAKE) test
	$(MAKE) build
