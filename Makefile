.PHONY: install dev build lint typecheck clean api-install api-test api-run up down logs

install:
	cd apps/web && npm install

dev:
	cd apps/web && npm run dev

build:
	cd apps/web && npm run build

lint:
	cd apps/web && npm run lint

typecheck:
	cd apps/web && npm run typecheck

clean:
	cd apps/web && rm -rf .next node_modules

# --- Phase 2: FastAPI + infrastructure -------------------------------------
# Windows defaults; on POSIX replace `.venv/Scripts/python` with `.venv/bin/python`.

api-install:
	py -3.11 -m venv apps/api/.venv
	apps/api/.venv/Scripts/python -m pip install -r apps/api/requirements-dev.txt

api-test:
	cd apps/api && .venv/Scripts/python -m pytest

api-run:
	cd apps/api && .venv/Scripts/python -m uvicorn src.main:app --reload --port 8000

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f api
