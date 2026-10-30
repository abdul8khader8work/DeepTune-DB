# DeepTune developer Makefile.
#
# Patch 2: cross-platform. The virtualenv interpreter is selected from $(OS)
# instead of hard-coding `.venv/Scripts/python` (Windows) everywhere, and
# PYTHONPATH is exported with the syntax of the host shell. Override any value
# on the command line, e.g. `make api-test PYTHON=.venv/bin/python`.
#
# GNU make on Windows runs recipes through cmd.exe, so every recipe below sticks
# to `cd <dir> && <command>` and forward slashes.

ifeq ($(OS),Windows_NT)
  # `py -3.11` matches the version the project was built and tested with.
  BASE_PYTHON ?= py -3.11
  PYTHON      ?= .venv/Scripts/python.exe
  ENV_PATH    := set PYTHONPATH=src&&
else
  BASE_PYTHON ?= python3
  PYTHON      ?= .venv/bin/python
  ENV_PATH    := PYTHONPATH=src
endif

API_DIR := apps/api
ML_DIR  := packages/ml-engine

.PHONY: install dev build lint typecheck clean api-install api-test api-run \
	ml-install ml-test ml-train ml-train-full ml-eval ml-export \
	up down logs logs-web

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
	$(BASE_PYTHON) -c "import shutil; [shutil.rmtree(path, ignore_errors=True) for path in ('apps/web/.next', 'apps/web/node_modules')]"

# --- Phase 2: FastAPI + infrastructure -------------------------------------
# $(PYTHON) is relative to the directory a recipe has cd'd into.

api-install:
	$(BASE_PYTHON) -m venv $(API_DIR)/.venv
	$(API_DIR)/$(PYTHON) -m pip install -r $(API_DIR)/requirements-dev.txt
	$(API_DIR)/$(PYTHON) -m pip install -r $(API_DIR)/requirements-ml.txt

api-test:
	cd $(API_DIR) && $(PYTHON) -m pytest

api-run:
	cd $(API_DIR) && $(PYTHON) -m uvicorn src.main:app --reload --port 8000

# --- Phase 3: neuro-symbolic ML engine -------------------------------------

ml-install:
	$(BASE_PYTHON) -m venv $(ML_DIR)/.venv
	$(ML_DIR)/$(PYTHON) -m pip install -r $(ML_DIR)/requirements-dev.txt

ml-test:
	cd $(ML_DIR) && $(PYTHON) -m pytest

# Patch 0 quick recipe: 20 epochs, 5,000 synthetic TPC-H-like graphs.
ml-train:
	cd $(ML_DIR) && $(ENV_PATH) $(PYTHON) -m training.train --epochs 20 --train-per-tier 1500 1700 1800 --val-size 150 --test-size 200 --out weights/demo-final.pt

# Quality-gated recipe used for the shipped checkpoint (Enforcer target rho > 0.85).
ml-train-full:
	cd $(ML_DIR) && $(ENV_PATH) $(PYTHON) -m training.train --epochs 120 --train-per-tier 1500 1700 1800 --val-size 150 --test-size 200 --out weights/demo-final.pt

ml-eval:
	cd $(ML_DIR) && $(ENV_PATH) $(PYTHON) -m training.evaluate --checkpoint weights/demo-final.pt --tier 3

# Patch 1: parity-gated ONNX export; the API scores plans with onnxruntime when the
# artifact sits next to the checkpoint. The .onnx file is git-ignored like the .pt.
ml-export:
	cd $(ML_DIR) && $(ENV_PATH) $(PYTHON) -m training.export_onnx --checkpoint weights/demo-final.pt --out weights/demo-final.onnx

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f api

logs-web:
	docker compose logs -f web
