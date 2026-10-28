# Phase 3 — Neuro-Symbolic ML Engine

**Status:** Complete (unit-tested; trained and evaluated on a synthetic EXPLAIN workload)
**Scope:** `packages/ml-engine/`, plus root `README.md`, `Makefile`, and this record.
**Source of truth:** `GOD_FILE.docx`, `MASTER_EXECUTION_PLAN.md.docx`, `REVIEWER&Enforcer.docx`,
`ML_Pipeline_and_Model_Training.docx`, `Evaluation_and_Benchmarking_Strategy.docx`.

The engine is a pure PyTorch/PyG library. It never imports FastAPI, uvicorn, SQLAlchemy, or a
database driver, and it contains no HTTP or persistence code. Phase 4 loads `PlanOptimizer` once
from the API lifespan and calls it per request.

## Deliverables

| Package | Files | Responsibility |
|---|---|---|
| `src/parsers` | `explain.py`, `schema.py` | `EXPLAIN (FORMAT JSON)` → PyG `Data`; catalog/stat dataclasses |
| `src/models` | `gatv2.py`, `checkpoint.py` | 3-layer GATv2 + global attention pooling; checkpoint save/load |
| `src/search` | `symbolic.py`, `beam.py`, `types.py` | Predicate extraction, pruning rules, beam search, scorers |
| `src/training` | `workload.py`, `dataset.py`, `metrics.py`, `evaluation.py`, `train.py`, `evaluate.py` | Synthetic curriculum workload, loaders, metrics, CLIs |
| `src` | `config.py`, `inference.py` | Feature vocabularies/limits; `PlanOptimizer` facade |
| `tests` | 8 files | 70 tests covering every package and the boundary rules |

## Graph contract

- Node features (39): 33-operator one-hot, `log1p(plan_rows)`, `log1p(actual_rows)`,
  `log1p(total_cost)`, `log1p(relation_bytes)`, selectivity, `is_index_scan`.
- Edge features (10): `log1p(cardinality)`, `log1p(data_size)`, 8-way join-type one-hot.
- Edges point **child → parent**, so message passing flows bottom-up from scans to the root.
- Traversal is iterative with a 5,000-node guard; a 401-node chain is covered by a test.
- The parser accepts a JSON object, a one-element JSON array, or a JSON string, and rejects
  payloads without a `Plan`/`Node Type`, non-JSON strings, and over-limit plans.

## Model contract

```
input projection 39 -> 128
GATv2Conv(128 -> 128, heads=4, edge_dim=10)
GATv2Conv(128 -> 128, heads=4, edge_dim=10)
GATv2Conv(128 -> 128, heads=1, edge_dim=10)
GlobalAttentionPooling(128)
MLP 128 -> 64 -> 1
dropout 0.2
```

- Exactly three GATv2 layers, hidden width 128, head counts 4 → 4 → 1.
- `LayerNorm` after each GATv2 layer keeps the eval-mode activation scale stable.
- Dropout 0.2 is applied after the input projection and inside the output MLP. Attention dropout
  inside `GATv2Conv` is disabled: dropping attention coefficients made the eval-mode attention
  distribution diverge from training and collapsed the regressor's output scale. This is an
  implementation detail, not a change to the 0.2 dropout contract.
- Trainable parameters: **126,210**.
- Attention weights from the last layer are normalised per target node and surfaced as
  `NodeAttention` records for the Phase 4 explainability panel.
- Inference always uses `torch.no_grad()`; `ModelScorer` and `Gatv2CostModel.predict_log_latency`
  both enforce it.

## Symbolic pruning

`generate_candidates` parses one read-only PostgreSQL `SELECT` with `sqlglot` (never regex) and
rejects DML/DDL/transaction nodes. Predicates are extracted from `WHERE`, `JOIN ... ON`,
`GROUP BY`, and `ORDER BY`, then resolved against the catalog.

| Rule | Behaviour |
|---|---|
| Boolean columns | Rejected as low-selectivity |
| JSONB without containment/text operator | Rejected; containment (`@>`, `<@`, `?`, `?|`, `?&`) maps to GIN |
| Distinct ratio < 5% | Rejected |
| Existing index | Single-column duplicate rejected |
| Composite order | Only left prefixes of the ranked predicate list are emitted |
| Access method | Equality/range → B-tree; JSON containment → GIN; optional equality → Hash |
| Storage | Index estimate must stay below 15% of the table |
| Write-heavy tables | At most 3 candidate indexes |
| DDL | Only `CREATE INDEX CONCURRENTLY ... USING ...` text for user review |

Candidates are deterministic (`uuid5`), capped at 12, and ordered by predicate priority. Every
discarded alternative is recorded as a `PruningRejection` so the UI can explain what was pruned.

## Beam search

- Width 5, at most 3 indexes per configuration, at most one index per table.
- Configurations are ranked by predicted log latency; the GNN scorer runs under `torch.no_grad()`.
- Within a 5% latency band, the configuration with the lowest write amplification wins; the next
  tie-break is fewer indexes, then lower latency.
- Per-table storage is checked again during expansion.
- `HeuristicPlanBuilder` is the Phase 3 stand-in for hypopg: it flips matching scans to index scans,
  shrinks their cost/rows, and rolls the savings up to the root cost. Phase 4 injects the real
  hypopg-modified plan through `candidate_plan_builder`; the interface is unchanged.
- Speedups use the measured baseline (`Execution Time`) when present, otherwise the model baseline.

## Training

- Target: `log1p(execution_time_ms)`; loss: `HuberLoss(delta=1.0)`.
- Optimizer: AdamW, learning rate 1e-3, weight decay 1e-5.
- Scheduler: `CosineAnnealingWarmRestarts(T_0=10, T_mult=1, eta_min=1e-5)`.
- Curriculum: epochs 1–20 simple scans, 21–50 joins, 51+ complex multi-join plans.
- Edge dropout 0.1 during training.
- Validation mixes tiers 1–3; the best checkpoint is selected by validation Spearman ρ, not by a
  loss value.
- The synthetic workload is a deterministic stand-in for real `EXPLAIN (ANALYZE)` data. It covers
  three tiers and uses a TPC-H-like demo catalog. Label noise is deliberately small so the reported
  rank correlation measures the model rather than irreducible generator noise.

### Measured results

Checkpoint: `weights/demo-final.pt` (120 epochs, 400/500/800 samples per tier, seed 7).
Metrics are on held-out synthetic plans; the GNN is a regressor, so accuracy is never reported.

| Split | MAE (ms) | RMSE (ms) | Spearman ρ | Median Q-error | MAPE |
|---|---:|---:|---:|---:|---:|
| Validation (mixed tiers) | 87.09 | 151.00 | **0.9901** | 1.130 | 13.01% |
| Test, tier 3 (training run, n=200) | 167.77 | 225.59 | **0.9274** | 1.142 | 13.16% |
| Test, tier 1 (`--seed 999`) | 16.82 | 28.48 | **0.9821** | 1.163 | — |
| Test, tier 2 (`--seed 999`) | 75.24 | 97.10 | **0.9602** | 1.146 | — |
| Test, tier 3 (`--seed 999`) | 160.83 | 226.08 | **0.9071** | 1.122 | — |

The target ρ > 0.85 is met on every tier. The checkpoint is not committed (`*.pt` and
`packages/ml-engine/weights/` are git-ignored).

## Inference facade

```python
from inference import InferenceConfig, PlanOptimizer

optimizer = PlanOptimizer(InferenceConfig(checkpoint_path="weights/demo-final.pt"))
report = optimizer.optimize(sql=sql, plan=explain_json, catalog=catalog)

report.baseline_latency_ms
report.recommendations      # CREATE INDEX CONCURRENTLY + speedup + confidence + explanation
report.configurations       # ranked beam configurations
report.attention            # top attention hotspots
report.rejected             # symbolic pruning audit trail
```

`PlanOptimizer.rank_configurations` exposes the ranked list without building recommendation text.
`load_optimizer` mirrors the Phase 4 lifespan usage.

## Verification

Run from `packages/ml-engine/` with Python 3.11:

| Command | Result |
|---|---|
| `python -m pytest` | **70 passed** (parser, pruning, model, beam, metrics, workload, inference, boundary checks) |
| `python -m compileall -q src tests` | Pass |
| `python -m training.train --epochs 120 --train-per-tier 400 500 800 --val-size 150 --test-size 200 --out weights/demo-final.pt` | Completes; writes checkpoint + `.metrics.json` |
| `python -m training.evaluate --checkpoint weights/demo-final.pt --tier 3` | ρ = 0.91–0.93 on held-out plans |

Not executed on this machine: a real PostgreSQL/hypopg round-trip. Docker and the `hypopg`
extension are unavailable locally, so Phase 3 ships the deterministic `HeuristicPlanBuilder` and
synthetic workload; Phase 4 supplies real hypopg plans through the same interface.

## Reviewer checklist

- [x] Only `packages/ml-engine/`, root `README.md`, `Makefile`, and this record touched.
- [x] No `fastapi`, `uvicorn`, `sqlalchemy`, `asyncpg`, or `psycopg` import anywhere in `src/`
      (enforced by `tests/test_architecture.py`).
- [x] No ML training logic in the API; the engine is an inference library.
- [x] No regex SQL sanitising; `sqlglot` AST + single read-only `SELECT` only.
- [x] No DDL is applied to a target database; only `CREATE INDEX CONCURRENTLY` text is emitted.
- [x] Model loaded once by `PlanOptimizer`; all inference under `torch.no_grad()`.
- [x] Metrics are MAE, RMSE, Spearman ρ, median Q-error, and MAPE; no accuracy metric.
- [x] Weights and checkpoints are git-ignored.
- [x] `CREATE INDEX CONCURRENTLY`, 15% storage cap, 3-index write-heavy cap, and 5% tie-break are
      covered by tests.
- [x] Exactly 3 GATv2 layers with 4 → 4 → 1 heads and a 128 → 64 → 1 output MLP.

## Deferred to Phase 4

- Real `EXPLAIN (ANALYZE, FORMAT JSON)` collection and hypopg-modified plans.
- Wiring `PlanOptimizer` into the FastAPI lifespan and the `/queries/analyze` pipeline.
- Streaming attention/DAG updates to the web console.
- Persisting training metrics and checkpoint metadata in the metadata database.
