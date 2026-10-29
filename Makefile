.PHONY: install dev build lint typecheck clean api-install api-test api-run ml-install ml-test ml-train ml-train-full ml-eval ml-export up down logs

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
	apps/api/.venv/Scripts/python -m pip install -r apps/api/requirements-ml.txt

api-test:
	cd apps/api && .venv/Scripts/python -m pytest

api-run:
	cd apps/api && .venv/Scripts/python -m uvicorn src.main:app --reload --port 8000

# --- Phase 3: neuro-symbolic ML engine -------------------------------------

ml-install:
	py -3.11 -m venv packages/ml-engine/.venv
	packages/ml-engine/.venv/Scripts/python -m pip install -r packages/ml-engine/requirements-dev.txt

ml-test:
	cd packages/ml-engine && .venv/Scripts/python -m pytest

# Patch 0 quick recipe: 20 epochs, 5,000 synthetic TPC-H-like graphs.
ml-train:
	cd packages/ml-engine && PYTHONPATH=src .venv/Scripts/python -m training.train --epochs 20 --train-per-tier 1500 1700 1800 --val-size 150 --test-size 200 --out weights/demo-final.pt

# Quality-gated recipe used for the shipped checkpoint (Enforcer target rho > 0.85).
ml-train-full:
	cd packages/ml-engine && PYTHONPATH=src .venv/Scripts/python -m training.train --epochs 120 --train-per-tier 1500 1700 1800 --val-size 150 --test-size 200 --out weights/demo-final.pt

ml-eval:
	cd packages/ml-engine && PYTHONPATH=src .venv/Scripts/python -m training.evaluate --checkpoint weights/demo-final.pt --tier 3

# Patch 1: parity-gated ONNX export; the API scores plans with onnxruntime when the
# artifact sits next to the checkpoint. The .onnx file is git-ignored like the .pt.
ml-export:
	cd packages/ml-engine && PYTHONPATH=src .venv/Scripts/python -m training.export_onnx --checkpoint weights/demo-final.pt --out weights/demo-final.onnx

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f api
