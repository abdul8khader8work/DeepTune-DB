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
  backend, device, runtime, checkpoint, parameter count, hidden width, layer count, and head count.
  `runtime` is `onnx` when `weights/demo-final.onnx` sits next to the checkpoint, `torch` when only the
  `.pt` is present, and `heuristic` when nothing loaded. The status bar renders it as a small badge.

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
| Every candidate pruned: "storage overhead exceeds 15% of the table" | A btree entry costs `8·columns + 6` bytes/row while the catalog's "row width" summed only column data — no tuple header, no page overhead — so the 15 % denominator was ~40 % too small | `parsers/schema.py` adds `TUPLE_HEADER_BYTES = 24` and `PAGE_OVERHEAD_RATIO = 1.25` to the fallback size estimate; `STORAGE_BUDGET_RATIO` stays at the blueprint's **15 %** |
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
server → {"type": "thinking"}
server → {"type": "tool",  "tool": "read_plan", "args": "run ...", "result": "...", "status": "done"}
server → {"type": "token", "text": "The "}      (3-char chunks, 20 ms per character)
server → {"type": "done",  "run_id": "..."}
```

- Auth reuses the HS256 token as a query parameter (browsers cannot set handshake headers).
- Close codes: `4401` missing/invalid token, `4404` unknown or unfinished run, `1011` internal fault.
- Questions are routed by intent: attention/why, risk/write/storage, reject/prune, index/SQL, and
  slow/latency. Anything else returns the full summary.
- Every answer is prefixed by deterministic `tool` frames (`read_plan`, `gnn_attention`,
  `symbolic_filter`, `hypopg_validate`) that record which slice of the report the prose came from.
  The UI renders them as tool-call chips above the message.
- The socket explains; it never mutates state and never calls the model.

### Streaming illusion (Patch 1)

The prose is real, the pace is staged. Two knobs, both configurable and both zeroed in tests:

| Setting | Default | Effect |
|---|---:|---|
| `COPILOT_STREAM_DELAY_MS` | 20 | per **character**; a 3-character chunk costs 60 ms (~50 chars/s) |
| `COPILOT_THINKING_DELAY_MS` | 500 | pause after each `thinking` frame, before its `tool` frame |

- `explainer.chunk()` flattens the sentences into fixed 3-character chunks; joining them reproduces
  the text exactly, so the typewriter never eats a space at a boundary.
- Each `tool` frame is preceded by a `thinking` frame and a 500 ms pause, so the trace reads as an
  agent deciding what to inspect rather than a script firing three chips at once.
- The client clears its indicator on any frame that is not `thinking`, so the state cannot get stuck.
- `ToolCallChip` renders `[tool] → result` collapsed and reveals `args` / full `result` on click.
- A caret pulses at the end of the message while `streaming` is true.

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
| `src/lib/morph.ts` | the time-travel motion value the node cards subscribe to (Patch 3) |
| `src/store/useSessionStore.ts` | health/engine probe, demo connection, schema fetch |
| `src/store/useAnalysisStore.ts` | analyze → poll → results state machine |
| `src/store/useCopilotStore.ts` | WebSocket lifecycle, token accumulation, `thinking` state, tool list |
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

### 6.1 The DAG morph (Patch 3)

The time-travel slider used to rebuild the whole plan on every tick: `blendPlans()` produced a new
node array, `QOGraph` re-rendered, and React Flow re-measured every node. Measured on the sample
plan, a 1.5 s scrub ran at **23.1 fps** (`layout`), 21.8 fps (`layout="position"`) and 25.4 fps
with no layout animation at all — the cost was the re-render, not the animation.

The morph is now a Framer Motion value:

| Piece | File | Role |
|---|---|---|
| `morphProgress` | `src/lib/morph.ts` | module-level `motionValue(0)`; the single source of morph position |
| `QOGraph` | `src/components/center/QOGraph.tsx` | renders **one** plan, attaches `data.counterpart` (the optimized node with the same id), and syncs the store → motion value through `useGraphStore.subscribe` — no React state |
| `QONode` | `src/components/center/QONode.tsx` | `layout` on the inner card only, tone washes as `opacity` motion values, `AnimatePresence` label swap, `will-change: transform` |
| `MorphValue` | `src/components/center/QOMetric.tsx` | subscribes to `morphProgress` and writes the interpolated number to `textContent` |
| `blendPlans` | removed | dead once the nodes stay stable |

- React renders **twice** per scrub, at the 50% identity flip, when the operator label, icon,
  border and bottleneck tone actually change. Everything numeric is a DOM write.
- `layout` stays on the inner `motion.div`; the outer React Flow wrapper keeps owning absolute
  positioning, so Framer never fights the canvas.
- Offline, `optimizedPlanNodes` in `src/lib/mock-plan.ts` supplies the counterpart so the slider
  still demonstrates the morph before the first analysis. A live run always uses the API payload.
- Result: **60.0 fps** (median 16.7 ms, p95 17.1 ms, max 17.3 ms over 91 frames) in the production
  build, with zero console errors.

## 7. Infrastructure

- `docker-compose.yml` now builds the API from the **repository root** (`context: .`,
  `dockerfile: apps/api/Dockerfile`) so the image can see `packages/ml-engine`.
- The image installs `requirements.txt` and then `requirements-ml.txt` from the CPU-only PyTorch
  index, copies `packages/ml-engine/src`, and sets `ML_*` env vars.
- Weights are **not** baked into the image (they are git-ignored). Compose mounts
  `./packages/ml-engine/weights` read-only; an empty directory is a supported state that degrades to
  heuristics.
- `.dockerignore` at the repo root keeps `apps/web`, `docs`, virtualenvs, node_modules, and weights
  out of the API build context; `apps/web/.dockerignore` does the same for the frontend image.
- Patch 2 adds the `web` service (`apps/web/Dockerfile`, multi-stage `node:20-alpine`). Its
  `NEXT_PUBLIC_API_URL`/`NEXT_PUBLIC_WS_URL` are build args because Next inlines them at build
  time; the container serves on `127.0.0.1:3000`.

## 8. Verification

| Command | Result |
|---|---|
| `apps/api`: `python -m pytest` | **68 passed** |
| `packages/ml-engine`: `python -m pytest` | **79 passed** |
| `apps/web`: `npm run typecheck` | Clean (strict, `noUncheckedIndexedAccess`) |
| `apps/web`: `npm run build` | Compiled successfully; `/` at 149 kB |
| Engine smoke (no DB) | runtime `onnx`, 126,210 params, layers 3, heads 4; 3 symbolic candidates; 1 recommendation `idx_orders_status_customer_id`; 1.31× predicted; optimized DAG + edges + trace correct; near-uniform attention flagged |

New API tests: `tests/test_ml_bridge.py` (graph round-trip, edge flip, attention fallback, id
namespacing, metric scaling), `tests/test_engine.py` (disabled / missing source / missing
checkpoint / corrupt checkpoint / real checkpoint), `tests/test_engine_api.py` (public status route,
reported runtime, copilot streaming, thinking-before-tool ordering, 3-character chunks, follow-up
routing, 4401, 4404).

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
