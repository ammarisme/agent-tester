# Agent Tester — developer tasks. `make help` lists them.
SHELL := /bin/bash
VENV ?= .venv
PY := $(VENV)/bin/python
BIN := $(VENV)/bin
UI := controller/frontend

.DEFAULT_GOAL := help
.PHONY: help setup dev up down logs test test-tester test-api lint fmt typecheck schemas smoke check

help: ## Show this help
	@grep -hE '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

# First Python >= 3.10 on PATH (macOS ships 3.9 as python3).
PYTHON ?= $(shell for p in python3.13 python3.12 python3.11 python3.10 python3; do \
  command -v $$p >/dev/null && $$p -c 'import sys; sys.exit(sys.version_info < (3, 10))' && { echo $$p; break; }; done)

$(PY):
	@test -n "$(PYTHON)" || { echo "Python 3.10+ is required"; exit 1; }
	$(PYTHON) -m venv $(VENV)

setup: $(PY) ## Install Python and Node dependencies for local development
	$(BIN)/pip install -q --upgrade pip
	$(BIN)/pip install -q -e "tester[dev]" -r controller/backend/requirements-dev.txt -r mocks/requirements.txt
	cd $(UI) && npm ci --no-audit --no-fund

dev: ## Run mock agent (:9999), API (:8000) and UI (:3000) locally with hot reload
	@mkdir -p data
	@trap 'kill 0' EXIT; \
	(cd mocks && ../$(BIN)/uvicorn echo_agent:app --port 9999 --log-level warning) & \
	(cd controller/backend && DATABASE_PATH=../../data/dev.db DEMO_AGENT_URL=http://127.0.0.1:9999 \
	  ../../$(BIN)/uvicorn app.main:app --port 8000 --reload --reload-dir app --reload-dir ../../tester/agent_tester) & \
	(cd $(UI) && API_INTERNAL_URL=http://127.0.0.1:8000 npx next dev -p 3000) & \
	wait

up: ## Build and start the Docker Compose stack
	docker compose up --build -d
	@echo "UI: http://localhost:$${UI_PORT:-3000}   API docs: http://localhost:$${UI_PORT:-3000}/api/docs"

down: ## Stop the Docker Compose stack (data volume is kept)
	docker compose down

logs: ## Follow controller logs
	docker compose logs -f controller

test: test-tester test-api ## Run all tests

test-tester:
	cd tester && ../$(BIN)/pytest -q

test-api:
	cd controller/backend && ../../$(BIN)/pytest -q -p no:logging

lint: ## Lint Python and TypeScript
	$(BIN)/ruff check tester controller/backend mocks
	$(BIN)/ruff format --check tester controller/backend mocks
	cd $(UI) && npx eslint .

fmt: ## Auto-format Python
	$(BIN)/ruff check --fix tester controller/backend mocks
	$(BIN)/ruff format tester controller/backend mocks

typecheck: ## Type-check the UI
	cd $(UI) && npx tsc --noEmit

schemas: ## Regenerate shared/schemas from the Pydantic models
	@for pair in contract:agent_contract case:case dataset:dataset job:job results:results; do \
	  name=$${pair%%:*}; file=$${pair##*:}; \
	  $(BIN)/agent-tester schema $$name > shared/schemas/$$file.schema.json; \
	done
	@echo "shared/schemas updated"

smoke: ## Run the CLI against the local mock agent (start it with `make dev`)
	$(BIN)/agent-tester run --agent presets/mock-echo.json --agent presets/mock-flaky.json \
	  --dataset datasets/samples/smoke.jsonl --param base_url=http://127.0.0.1:9999 --repeats 3

check: lint typecheck test ## Everything CI runs, locally
