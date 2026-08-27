.PHONY: setup dev-web dev-api test build check

API_PORT ?= 8000

setup:
	python3 -m venv .venv
	.venv/bin/pip install -r apps/api/requirements.txt
	npm install

dev-web:
	npm run dev

dev-api:
	cd apps/api && ../../.venv/bin/uvicorn app.main:app --reload --port $(API_PORT)

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
