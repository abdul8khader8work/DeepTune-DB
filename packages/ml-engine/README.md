# DeepTune ML Engine (Phase 3)

Pure PyTorch/PyG core for the neuro-symbolic optimizer. No web framework, no
database driver, no training logic in `apps/api`.

```
packages/ml-engine/
├── src/
│   ├── parsers/      # EXPLAIN JSON -> PyG Data
│   ├── models/       # 3-layer GATv2 + global attention pooling
│   ├── search/       # symbolic pruning + GNN-guided beam search
│   ├── training/     # synthetic workload, curriculum training, metrics
│   ├── config.py     # feature vocabularies and engine limits
│   └── inference.py  # PlanOptimizer facade (loaded once by the API in Phase 4)
├── tests/
├── weights/          # git-ignored .pt checkpoints
├── requirements.txt
└── setup.py
```

## Setup

```bash
cd packages/ml-engine
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt   # POSIX: .venv/bin/python
.venv/Scripts/python -m pytest                                # 70 tests
```

## Train the demo checkpoint

```bash
cd packages/ml-engine
PYTHONPATH=src .venv/Scripts/python -m training.train \
  --epochs 120 --train-per-tier 400 500 800 --val-size 150 --test-size 200 \
  --out weights/demo-final.pt
PYTHONPATH=src .venv/Scripts/python -m training.evaluate \
  --checkpoint weights/demo-final.pt --tier 3
```

`PYTHONPATH=src` is only needed for the module CLIs; installing with
`pip install -e .` also works. Weights are never committed. The reported
held-out tier-3 result is ρ = 0.93 with MAE = 168 ms; see
`docs/phase-3-ml-engine.md` for the full table.

## Inference

```python
from inference import InferenceConfig, PlanOptimizer

optimizer = PlanOptimizer(InferenceConfig(checkpoint_path="weights/demo-final.pt"))
report = optimizer.optimize(sql=sql, plan=explain_json, catalog=catalog)
```

The facade loads the model once, builds the base QEP graph, runs symbolic
pruning, scores candidate configurations with `torch.no_grad()`, and returns
reviewable `CREATE INDEX CONCURRENTLY` scripts. Phase 4 passes hypopg-modified
plans through `candidate_plan_builder`; Phase 3 ships a deterministic
`HeuristicPlanBuilder` for standalone use.

## Metrics

Regression is evaluated with MAE, RMSE, Spearman rank correlation, median
Q-error, and MAPE. "Accuracy" is never used for the cost model.
