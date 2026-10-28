# Phase 4 — Integration & Wow Factor

**Status:** Complete (web → API → engine wired; verified locally without Docker)
**Scope:** `apps/api/` (integration only), `apps/web/` (live data), `infra/` (image + compose),
plus root `README.md`, `Makefile`, `.env.example`, and this record.
**Source of truth:** `GOD_FILE.docx`, `MASTER_EXECUTION_PLAN.md.docx`, `REVIEWER&Enforcer.docx`.

Phase 4 does not add new model code or new UI concepts. It replaces every Phase 1 mock with a real
data path and makes the three layers run as one system:

```
Monaco SQL ──▶ POST /queries/analyze ──▶ sqlglot guard ──▶ EXPLAIN (ANALYZE) in a rolled-back txn
                                             │
                                             ▼
                              build_dag (API contract) ──▶ PlanGraph (PyG)
                                             │
                                             ▼
                        symbolic pruning ──▶ GATv2 beam search ──▶ best configuration
                                             │
                                             ▼
                   hypopg validation in the shadow DB ──▶ CREATE INDEX CONCURRENTLY text
                                             │
              GET /queries/{id}/results ◀────┘
                       │
        ┌──────────────┼───────────────────────┐
        ▼              ▼                       ▼
   React Flow     Hero metrics          WS /ws/copilot/{id}
   (live DAG)     (speedup)             (streamed explanation)
```

## 1. Engine lifecycle

`apps/api/src/services/engine.py` owns the single `PlanOptimizer` instance.

- Loaded **once** in the FastAPI `lifespan`, via `asyncio.to_thread(load_engine, settings)`, so the
  126,210-parameter checkpoint never blocks the event loop and is **never** loaded in a route.
- The engine is not a published wheel, so the loader appends `packages/ml-engine/src` to `sys.path`
  and imports the `inference` facade. `ML_ENGINE_SRC` / `ML_CHECKPOINT_PATH` override the layout.
- The loader is total: `ML_ENABLED=false`, a missing source tree, a missing checkpoint, or a corrupt
  file all produce `EngineStatus(backend="heuristic", error=...)` instead of a failed startup.
- `GET /api/v1/engine/status` is public (the shell needs it before a token is pasted) and reports
  backend, device, checkpoint, parameter count, hidden width, layer count, and head count.

`apps/api/src/services/ml.py` is the only bridge between the engine and the API contracts. It is
torch-free and engine-import-free at module scope, so it is unit-testable with plain fakes:

| Engine value | API field | Notes |
|---|---|---|
| `report.recommendations[].sql_statement` | `IndexRecommendation.sql_statement` | already `CREATE INDEX CONCURRENTLY` |
| candidate `id` | `IndexRecommendation.id` | namespaced as `{run_id}:{candidate_id}` |
| `report.plan_graph` | `optimized_dag` + `edges` | rebuilt from PyG tensors, no re-parsing |
| `report.attention` | `attention[]` + `gnn_attention_score` | per-node GATv2 weights |
| `report.rejected` | `rejected_candidates[]` | symbolic audit trail |
| `report.trace` | `symbolic_trace[]` | beam-search narration |
| `report.configurations[0].predicted_speedup` | `speedup_factor` | falls back to a latency ratio |

Node identity is stable: `plan_to_graph` and `services/dag.build_dag` both walk the EXPLAIN tree
pre-order, so graph node `i` maps to API `node_{i+1}`. Edge direction is flipped on the way out:
the engine stores child → parent (message passing flows upward), the API stores parent → child, and
`apps/web/src/lib/plan-adapter.ts` flips it again for React Flow's handle geometry.

## 2. Pipeline stages

`apps/api/src/services/pipeline.py` keeps the Phase 2 shape and adds an engine stage:

| Stage | Progress | Work |
|---|---|---|
| `parsing` | 5–30 % | sqlglot guard, target connect, `EXPLAIN (ANALYZE)` in a rolled-back transaction |
| `gnn_inference` | 60 % | `asyncio.to_thread(ml.optimize, ...)`: symbolic pruning + beam search |
| `hypopg_validation` | 80 % | inject each candidate into the shadow DB, keep the fastest plan |
| `gnn_inference` | 95 % | assemble explainability, recommendations, and the final `AnalysisResult` |

Every engine fault is caught at the stage boundary and downgraded to `_heuristic_stage`, which is
the Phase 2 candidate generator. A run therefore always completes with either a GNN plan or an
honest heuristic plan; `AnalysisResult.engine` tells the UI which one it got.

## 3. Calibration found during integration

Wiring the engine to real catalogs exposed three Phase 3 assumptions that rejected every realistic
candidate. All three fixes are small, documented, and covered by tests.

| Symptom | Cause | Fix |
|---|---|---|
| Every candidate pruned: "storage overhead exceeds 15% of the table" | A btree entry costs `8·columns + 6` bytes/row while the catalog's "row width" summed only column data — no tuple header, no page overhead | `parsers/schema.py` adds `TUPLE_HEADER_BYTES = 24` and `PAGE_OVERHEAD_RATIO = 1.25` to the fallback size estimate, and `STORAGE_BUDGET_RATIO` moves 0.15 → **0.40** |
| Heatmap rendered flat: every node at 1.0 | GATv2 emits near-uniform attention on out-of-distribution plan shapes | `ml.apply_attention` detects a normalised spread below `0.08`, falls back to cost weighting, and appends a trace note |
| Model metadata showed `layers: null` | `ModelConfig` names the field `layers`, not `num_layers` | loader reads `layers` |

The rejection message is now derived from the configured ratio (`f"{ratio:.0%}"`), so it can never
drift from the constant again.

## 4. Streaming copilot

`/api/v1/ws/copilot/{run_id}` is a deterministic explainer, not a language model. It is grounded
entirely in the finished `AnalysisResult`, which keeps the feature offline and honest.

```
client → {"type": "question", "text": "what is the write risk?"}
server → {"type": "ready", "run_id": "...", "engine": "gnn"}
server → {"type": "token", "text": "The "}      (word by word, COPILOT_STREAM_DELAY_MS apart)
server → {"type": "done",  "run_id": "..."}
```

- Auth reuses the HS256 token as a query parameter (browsers cannot set handshake headers).
- Close codes: `4401` missing/invalid token, `4404` unknown or unfinished run, `1011` internal fault.
- Questions are routed by intent: attention/why, risk/write/storage, reject/prune, index/SQL, and
  slow/latency. Anything else returns the full summary.
- The socket explains; it never mutates state and never calls the model.

## 5. Run archive

`apps/api/src/db/run_archive.py` makes runs survivable without changing the Phase 2 hot path:

- `PostgresRunArchive` upserts into `analysis_runs` (`engine`, `error`, `result::jsonb`,
  `updated_at`) on create/complete/fail.
- With no `METADATA_DB_DSN`, `NullRunArchive` is used and behaviour is identical to Phase 2.
- Archival failures are logged, never surfaced: a metadata DB fault cannot fail an analysis.

## 6. Frontend wiring

| File | Role |
|---|---|
| `src/types/api.ts` | strict mirror of the Pydantic contracts (no `any`) |
| `src/lib/api.ts` | typed client, uniform `ApiError`, bearer token from env or `localStorage` |
| `src/lib/plan-adapter.ts` | DAG → React Flow layout, depth from edges, hero metrics |
| `src/store/useSessionStore.ts` | health/engine probe, demo connection, schema fetch |
| `src/store/useAnalysisStore.ts` | analyze → poll → results state machine |
| `src/store/useCopilotStore.ts` | WebSocket lifecycle and token accumulation |
| `src/components/**` | live DAG, hero metrics, recommendation card, status bar, schema explorer |

Behaviour details:

- `AppShell` probes `/health` and `/engine/status` on mount, so the status bar shows the real
  backend (`GATv2 (neuro-symbolic)` vs `heuristic fallback`) instead of a hardcoded label.
- `Run & Optimize` sends the editor SQL with the selected goal (read / balanced / storage),
  polls status at 400 ms, and attaches the copilot socket when the run completes.
- The recommendation card copies the real SQL and applies/reverts the hypothetical index in the
  shadow DB. It keeps the Phase 1 sample plan as the offline fallback so the UI never looks broken
  when the API is down.
- If no database is connected, the schema explorer falls back to the sample catalog and the topbar
  pill reads "No database attached" in the warning tone.

## 7. Infrastructure

- `docker-compose.yml` now builds the API from the **repository root** (`context: .`,
  `dockerfile: apps/api/Dockerfile`) so the image can see `packages/ml-engine`.
- The image installs `requirements.txt` and then `requirements-ml.txt` from the CPU-only PyTorch
  index, copies `packages/ml-engine/src`, and sets `ML_*` env vars.
- Weights are **not** baked into the image (they are git-ignored). Compose mounts
  `./packages/ml-engine/weights` read-only; an empty directory is a supported state that degrades to
  heuristics.
- `.dockerignore` at the repo root keeps `apps/web`, `docs`, `.venv`, and weights out of the build
  context.

## 8. Verification

| Command | Result |
|---|---|
| `apps/api`: `python -m pytest` | **59 passed** |
| `packages/ml-engine`: `python -m pytest` | **70 passed** |
| `apps/web`: `npm run typecheck` | Clean (strict, `noUncheckedIndexedAccess`) |
| `apps/web`: `npm run build` | Compiled successfully; `/` at 148 kB |
| Engine smoke (no DB) | 126,210 params, layers 3, heads 4; 3 symbolic candidates; 1 recommendation `idx_orders_status_customer_id`; 1.31× predicted; optimized DAG + edges + trace correct; near-uniform attention flagged |

New API tests: `tests/test_ml_bridge.py` (graph round-trip, edge flip, attention fallback, id
namespacing, metric scaling), `tests/test_engine.py` (disabled / missing source / missing
checkpoint / corrupt checkpoint / real checkpoint), `tests/test_engine_api.py` (public status route,
copilot streaming, follow-up routing, 4401, 4404).

Not executed on this machine: the Docker image build and a live hypopg round-trip (Docker Desktop is
unavailable here). The compose file, Dockerfile, and shadow validation path are unchanged in
contract and covered by unit tests with fakes.

## 9. Reviewer checklist

- [x] `apps/web` imports no `torch`, `numpy`, `pandas`, or `packages/ml-engine`.
- [x] `apps/api` contains no training logic; the engine is imported as an inference library.
- [x] `packages/ml-engine` still imports no `fastapi`, `uvicorn`, or `sqlalchemy`
      (`tests/test_architecture.py`).
- [x] Model loaded once in `lifespan`, never in a route handler.
- [x] No regex SQL sanitising; `sqlglot` AST + transaction-wrapped `EXPLAIN` with rollback.
- [x] No DDL applied to the target DB; only `CREATE INDEX CONCURRENTLY` text is emitted.
- [x] No `any` in TypeScript; every prop and API response is typed.
- [x] Tailwind utilities only; no inline colour/layout styles; no pure black or light surfaces.
- [x] No React component file exceeds 200 lines.
- [x] MAE / RMSE / Spearman ρ remain the model metrics; no "accuracy" anywhere.
- [x] `.env`, credentials, and `.pt` weights remain git-ignored.

## 10. Deferred

- Real hypopg-modified plans fed back into the GNN (the engine currently scores the baseline graph
  and the heuristic plan builder; hypopg validates the winner).
- Persisting attention/explainability payloads for historical runs (only the result JSON is stored).
- Replacing the synthetic training workload with the collected real EXPLAIN corpus.
