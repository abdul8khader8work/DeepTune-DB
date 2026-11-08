# Phase 3 — Neuro-Symbolic ML Engine

**Status:** Complete (unit-tested; trained and evaluated on a synthetic EXPLAIN workload)
**Scope:** `packages/ml-engine/`, plus root `README.md`, `Makefile`, and this record.
**Source of truth:** `docs/blueprints/GOD_FILE.docx`, `docs/blueprints/MASTER_EXECUTION_PLAN.md.docx`,
`docs/blueprints/REVIEWER&Enforcer.docx`, `docs/blueprints/ML_Pipeline_and_Model_Training.docx`,
`docs/blueprints/Evaluation_and_Benchmarking_Strategy.docx`.

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
GATv2Conv(128 -> 128, heads=4, edge_dim=10)  + skip_proj(39 -> 128)
GlobalAttentionPooling(128)
MLP 128 -> 64 -> 1
dropout 0.2
```

- Two GATv2 layers, hidden width 128, head counts 4 → 4, plus a residual skip that adds the raw
  node features (projected 39 → 128) to the last layer's output:
  `H_out = activation(H2 + skip_proj(X))`. The third layer was removed because it over-smoothed
  shallow query plans (5–12 nodes), washing out the scan-level topology that explains latency.
- `LayerNorm` after each GATv2 layer keeps the eval-mode activation scale stable.
- Dropout 0.2 is applied after the input projection and inside the output MLP. Attention dropout
  inside `GATv2Conv` is disabled: dropping attention coefficients made the eval-mode attention
  distribution diverge from training and collapsed the regressor's output scale. This is an
  implementation detail, not a change to the 0.2 dropout contract.
- Trainable parameters: **96,514** (down from 126,210 after the layer removal).
- Attention weights from the last layer are averaged across the 4 heads, normalised per target
  node, and surfaced as `NodeAttention` records for the Phase 4 explainability panel.
- Inference always uses `torch.no_grad()`; `ModelScorer`, the beam loop inside
  `PlanOptimizer.optimize`, and `Gatv2CostModel.predict_log_latency` all enforce it.

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
| Storage | Index estimate must stay below the configured budget (15 % of the table, per the blueprint; see `docs/phase-4-integration.md` for the header-sizing fix) |
| Write-heavy tables | At most 3 candidate indexes |
| DDL | Only `CREATE INDEX CONCURRENTLY ... USING ...` text for user review |

Candidates are deterministic (`uuid5`), capped at 12, and ordered by predicate priority. Every
discarded alternative is recorded as a `PruningRejection` so the UI can explain what was pruned.

## Beam search

- Width 10, at most 3 indexes per configuration, at most one index per table.
- Configurations are ranked by predicted log latency; the GNN scorer runs under `torch.no_grad()`.
- Within a 5% latency band, the configuration with the lowest write amplification wins; the next
  tie-break is fewer indexes, then lower latency.
- Per-table storage is checked again during expansion.
- `enumerate_configurations` mirrors the expansion rules without scoring anything, so the API can
  prefetch a hypothetical plan for every configuration the search can reach (`plan_requests`).
- `_HypotheticalPlanBuilder` then scores the real post-`hypopg` plan supplied under
  `candidate_qeps`. `HeuristicPlanBuilder` remains the offline stand-in: it flips matching scans to
  index scans, shrinks their cost/rows, and rolls the savings up to the root cost, and it is used for
  any configuration the prefetcher did not cover.
- Speedups use the measured baseline (`Execution Time`) when present, otherwise the model baseline.

## Training

- Target: `log1p(execution_time_ms)`; loss: `HuberLoss(delta=1.0)`.
- Optimizer: AdamW, learning rate 1e-3, weight decay 1e-5.
- Scheduler: `CosineAnnealingWarmRestarts(T_0=10, T_mult=1, eta_min=1e-5)`.
- Curriculum: epochs 1–20 simple scans, 21–50 joins, 51+ complex multi-join plans. Short runs
  (`--epochs <= 20`) compress the same progression into thirds so every demo checkpoint sees all
  three tiers.
- Edge dropout 0.1 during training.
- Validation mixes tiers 1–3; the best checkpoint is selected by validation Spearman ρ, not by a
  loss value.
- Early stopping is tier-aware: stale-epoch counters reset at every tier transition and stopping is
  only permitted in the final tier, so a tier-1 model can never halt the curriculum early.
- The synthetic workload is a deterministic stand-in for real `EXPLAIN (ANALYZE)` data. It covers
  three tiers and uses a TPC-H-like demo catalog. Label noise is deliberately small so the reported
  rank correlation measures the model rather than irreducible generator noise.

### Measured results

Checkpoint: `weights/demo-final.pt` — the 2-layer residual model, fine-tuned for 90 epochs (best
epoch 62, early stop at 77) from the previous 3-layer 120-epoch weights over **5,000 synthetic
TPC-H-like QEP graphs** (`--train-per-tier 1500 1700 1800`), 150 validation and 200 held-out test
graphs, seed 7. The transfer keeps every unchanged tensor, drops the removed third block, and
zero-initialises the new `skip_proj`, so fine-tuning starts from the exact previous function.
Architecture: GATv2, 2 layers + residual, 128 hidden, 4 → 4 heads, Global Attention Pooling,
dropout 0.2, **96,514** parameters. Metrics are on held-out synthetic plans; the GNN is a
regressor, so accuracy is never reported.

| Split | MAE (ms) | RMSE (ms) | Spearman ρ | Median Q-error | MAPE |
|---|---:|---:|---:|---:|---:|
| Validation (mixed tiers) | 68.11 | 122.27 | **0.9926** | 1.080 | 8.73% |
| Test, mixed tiers (n=200) | 140.72 | 188.11 | **0.9609** | 1.113 | 11.00% |

The Enforcer's target ρ > 0.85 is met with margin. Compared with the previous 3-layer checkpoint on
the same held-out split (ρ 0.9643, MAE 91.22 ms, median Q-error 1.068), the residual model keeps the
rank correlation that the beam search depends on (0.9609) while removing 24% of the parameters
(126,210 → 96,514). Absolute error rises on this synthetic workload (median Q-error 1.068 → 1.113);
the trade is deliberate, because the Patch 2 mandate is to stop over-smoothing shallow plans rather
than to squeeze the last few milliseconds out of a generator that has no real plan variance.
`make ml-train` is the literal 20-epoch Patch 0 recipe; `make ml-train-full` is the full
quality-gated recipe. A 20-epoch run reaches ρ ≈ 0.67 on the held-out test split, so it is kept only
as a smoke recipe and never shipped. The checkpoint is not committed (`*.pt` and
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

## ONNX export and inference (Patch 1)

`torch.onnx.export` cannot trace `GATv2Conv` or `GlobalAttentionPooling` as written: both turn
tensors into Python ints mid-graph (`maybe_num_nodes` -> `int(edge_index.max()) + 1`, and
`batch.max().item()`). The tracer bakes the *trace-time* graph size into the artifact, so every plan
with a different node count is silently wrong — measured drift up to 5.07 in log-latency space
(≈160x in milliseconds) while the export itself reports success.

`src/models/onnx.py` therefore exports `OnnxExportModel`, a tensor-in/tensor-out mirror of the GATv2
forward that reuses the trained parameters by reference and stays shape-polymorphic:

| Naive PyG op | ONNX-safe replacement | Why |
|---|---|---|
| `scatter_add` / `index_add` | dense `[E, N]` indicator + `matmul` | ONNX leaves duplicate `ScatterElements` indices undefined |
| `torch_geometric.softmax` | per-target max + indicator normalisation | a global max underflows after two layers (score range > 300 nats) |
| `add_self_loops(fill_value='mean')` | per-target mean of incoming edge attributes | the loop feature is the mean of *in-edges*, not of the whole graph |

Verification is part of the export: `export_onnx(..., verify=True)` scores the trace graph through
onnxruntime, compares against the PyTorch forward, and deletes the artifact if the drift exceeds
`1e-3`. `tests/test_onnx.py` additionally checks 18 plans spanning 2–12 nodes, the attention output,
and the embedded metadata.

```bash
cd packages/ml-engine
PYTHONPATH=src .venv/Scripts/python -m training.export_onnx \
  --checkpoint weights/demo-final.pt --out weights/demo-final.onnx   # or: make ml-export
```

Measured on this machine (CPU, single thread, 36 plans of 2–12 nodes, 50 repeats each):

| Runtime | Median per plan | Max per plan |
|---|---:|---:|
| onnxruntime 1.31 (opset 17, 537,991 bytes) | **0.376 ms** | 0.519 ms |
| PyTorch 2.15 forward | 3.827 ms | 4.048 ms |

Worst `|torch - onnx|` across those 36 plans is `9.5e-07` log-latency units; attention drift is
`3.6e-07`. `PlanOptimizer` prefers `<checkpoint>.onnx` when it exists, keeps the `.pt` loaded for
metadata/config and for edge-less (single-node) plans where the attention softmax has nothing to
normalise, and reports the active path as `runtime` (`onnx` / `torch` / `heuristic`) in
`GET /api/v1/engine/status`. A corrupt or missing artifact degrades to torch and logs, never raises.

## Verification

Run from `packages/ml-engine/` with Python 3.11:

| Command | Result |
|---|---|
| `python -m pytest` | **79 passed** (parser, pruning, model, beam, metrics, workload, curriculum, inference, ONNX export/parity, boundary checks) |
| `python -m compileall -q src tests` | Pass |
| `python -m training.export_onnx --checkpoint weights/demo-final.pt --out weights/demo-final.onnx` | Verified export, opset 17, metadata embedded, median 0.32 ms |
| `python -m training.train --epochs 120 --train-per-tier 1500 1700 1800 --val-size 150 --test-size 200 --out weights/demo-final.pt` | Completes; builds 5,000 synthetic graphs and writes checkpoint + `.metrics.json` |
| `python -m training.train --epochs 20 --train-per-tier 1500 1700 1800 ...` | Completes (smoke recipe, all three tiers seen) |
| `python -m training.evaluate --checkpoint weights/demo-final.pt --tier 3` | ρ = 0.956 on held-out plans (tiers 1/2: 0.986 / 0.968) |

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
- [x] ONNX export is parity-gated against the PyTorch forward (drift > `1e-3` deletes the artifact).
- [x] Metrics are MAE, RMSE, Spearman ρ, median Q-error, and MAPE; no accuracy metric.
- [x] Weights and checkpoints are git-ignored.
- [x] `CREATE INDEX CONCURRENTLY`, the storage budget, the 3-index write-heavy cap, and the 5% tie-break are
      covered by tests.
- [x] Exactly 2 GATv2 layers with 4 → 4 heads, a residual skip, and a 128 → 64 → 1 output MLP.
- [x] Every beam configuration is scored on the post-`hypopg` plan when the API supplies one;
      missing plans fall back to the offline builder and the trace says how many did.

## Deferred to Phase 4

- Real `EXPLAIN (ANALYZE, FORMAT JSON)` collection and hypopg-modified plans (shipped in
  `docs/phase-4-integration.md`; Patch 2 Task 3 moved the plan fetch *before* the beam).
- Wiring `PlanOptimizer` into the FastAPI lifespan and the `/queries/analyze` pipeline (shipped).
- Streaming attention/DAG updates to the web console.
- Persisting training metrics and checkpoint metadata in the metadata database.
