# DeepTune

**A Lightweight, Neuro-Symbolic Query Optimizer and Index Recommender for Local Databases.**

DeepTune reads a PostgreSQL query plan, explains it visually, and recommends indexes that make it
faster — combining a Graph Neural Network (cost prediction) with symbolic rules and beam search.
Everything runs locally. No cloud APIs. No black-box guesses. The AI never executes DDL on your
database; it produces a script you review and apply yourself.

---

## Phase status

| Phase | Scope | Status |
|---|---|---|
| **1. UI Skeleton & Design System** | Next.js 14, 3-pane console, design tokens, dummy DAG | **Complete** |
| **2. Backend API & Security** | FastAPI, read-only role, `EXPLAIN` sandbox, `hypopg` shadow DB | **Complete** |
| **3. Neuro-Symbolic ML Engine** | JSON→PyG parser, GATv2, symbolic pruning, beam search | **Complete** |
| **4. Integration & Wow Factor** | Live DAG, real metrics, shadow-index apply, streaming Copilot | **Complete** |

All four phases are complete. The web console now runs against the live API and the trained engine:
`Run & Optimize` executes a real `EXPLAIN`, the GNN ranks index configurations, a real index built in
the disposable shadow database measures the validated speedup, and the copilot streams an
explanation of the result.

---

## Documentation

Everything lives under `docs/`:

| Path | Contents |
|---|---|
| `docs/README.md` | index of the documentation set |
| `docs/phase-1-ui-skeleton.md` | UI skeleton, design tokens, layout, dummy DAG |
| `docs/phase-2-backend-api.md` | FastAPI contracts, SQL guard, EXPLAIN sandbox, hypopg |
| `docs/phase-3-ml-engine.md` | parser, GATv2, pruning, beam search, metrics |
| `docs/phase-4-integration.md` | web → API → engine wiring, copilot, DAG morph |
| `docs/blueprints/` | the source-of-truth blueprint documents (`.docx`/`.pdf`/`.xlsx`) |

`AGENTS.md` (the project constitution) stays at the repository root because tooling reads it there.

---

## What is in Phase 1

- **3-pane command center** at 25% / 50% / 25%, resizable, with a 48px topbar and 32px statusbar.
- **Left — Control Tower:** Monaco SQL editor with tab chrome, format/clear actions, `Explain Only`
  and `Run & Optimize`, plus a searchable schema explorer.
- **Center — Visual Brain:** interactive React Flow DAG with custom `QONode` cards (cost, rows,
  selectivity, GNN attention), animated high-cardinality edges, zoom/fit/lock toolbar, plan toggle,
  heatmap switch, and a time-travel slider that morphs the DAG with Framer Motion — the card
  interpolates its cost/rows/selectivity/attention and swaps `Seq Scan` → `Index Scan` at the
  midpoint, at 60 fps (see `docs/phase-4-integration.md` §6.1).
- **Right — AI Insights:** hero latency metrics, recommendation card with confidence badge and
  `CREATE INDEX` script, and a Copilot chat shell with tool-call chips.
- **Global chrome:** connection pill, breadcrumbs, `⌘K` command palette, dark-only token system.
- **Zero backend logic, zero network calls.** All data is local mock data.

---

## What is in Phase 2

- **FastAPI service** at `apps/api/` with strict Pydantic v2 contracts and a uniform error
  envelope. Routes: connect, schema, analyze, status, results, apply/revert, health.
- **Read-only target access:** the `query_optimizer` role can only `SELECT`; the API never applies
  DDL to the target database.
- **EXPLAIN sandbox:** `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` runs inside a transaction with a
  5s `statement_timeout` and an unconditional rollback. Every latency uses the **median-of-5 runs
  protocol**: five executions, the fastest and slowest samples discarded, and the median of the
  remaining three reported, so Postgres caching cannot decide the number.
- **SQL guard:** `sqlglot` AST parsing rejects anything that is not exactly one read-only `SELECT`.
  No regex sanitising anywhere.
- **Shadow DB validation:** `hypopg` supplies the post-index QEP that the beam scores (a plain
  `EXPLAIN`, because hypopg only injects an index into an explain-only statement). The winning
  candidate is then built **for real** in the disk-backed PostgreSQL 16 shadow container
  (`shadow_data` named volume), measured with the median-of-N protocol, and dropped again. The
  approved SQL is still emitted as a reviewable `CREATE INDEX CONCURRENTLY` script; no DDL ever
  reaches the target database, and data no longer lives in `tmpfs`.
- **Security:** HS256 bearer tokens minted by `python -m src.cli.token`, Fernet-encrypted DSNs at
  rest, CORS locked to `http://localhost:3000`, and a per-IP rate limit on `/queries/analyze`.
- **Infrastructure:** `docker-compose.yml` runs metadata, target, shadow, API, web (Next.js), and
  nginx services with health checks and loopback-only ports.

See `docs/phase-2-backend-api.md` for the endpoint table and reviewer checklist.

---

## What is in Phase 3

- **Plan parser:** PostgreSQL `EXPLAIN (FORMAT JSON)` becomes a PyG graph with operator one-hot
  features, log-scaled rows/cost/size, selectivity, edge cardinality, and join-type embeddings.
- **GATv2 cost model:** two attention layers (128 wide, 4 → 4 heads) plus a residual skip that
  carries the raw node features around both layers, global attention pooling, and a 128 → 64 → 1
  head. It predicts `log1p(execution_time_ms)` and exposes per-node attention.
- **Symbolic pruning:** boolean/JSONB/low-distinct columns, duplicate indexes, left-prefix
  violations, the 15% storage budget, and the 3-index write-heavy cap are enforced before the GNN.
- **Beam search:** width 10, at most 3 indexes, one per table, ranked by predicted latency with a
  5% tie-break on write amplification. Every candidate configuration is planned through `hypopg`
  first, so the GNN scores the post-index QEP rather than the baseline. Only
  `CREATE INDEX CONCURRENTLY` text is emitted.
- **Training:** Huber loss, AdamW, cosine warm restarts, edge dropout, and the 1–20 / 21–50 / 51+
  curriculum. Validation uses MAE, RMSE, Spearman ρ, and median Q-error — never accuracy.
- **Measured result:** the shipped residual checkpoint (96,514 parameters) reaches **ρ = 0.961**,
  MAE 141 ms, and median Q-error 1.11 on the held-out synthetic test split. Weights stay
  git-ignored.
- **ONNX inference:** `make ml-export` writes `weights/demo-final.onnx` (opset 17, 400 KB) after
  proving parity against the PyTorch forward; the API then scores plans through onnxruntime in
  **0.28 ms** median per plan instead of 3.8 ms. The export is a hand-written, shape-polymorphic
  mirror of the GATv2 forward because a naive trace silently bakes the graph size in.

See `docs/phase-3-ml-engine.md` for the graph contract, pruning table, and full metrics.

---

## What is in Phase 4

- **One data path:** the console calls `POST /queries/analyze`, **opens a WebSocket stream** at
  `/ws/optimize/{run_id}`, receives real-time `log_update` / `progress` / `complete` events, and
  renders the returned DAG. The Phase 1 mock plan survives only as an offline fallback.
- **No polling:** `/queries/{run_id}/status` is deprecated and retained only for non-WebSocket
  clients; the console never calls it. Both sockets register in a connection registry and are
  unregistered in a `finally`, and uvicorn's 30s + 10s heartbeat evicts dead peers, so a closed
  tab cannot leak a zombie connection.
- **Engine loaded once:** `PlanOptimizer` is constructed in the FastAPI `lifespan` on a worker
  thread, never inside a route. `GET /engine/status` reports the loaded checkpoint, parameter count,
  device, layer/head configuration, and the active inference `runtime` (`onnx`, `torch`, or
  `heuristic`), which the status bar shows as a badge.
- **Real explainability:** GATv2 attention becomes the node heatmap, the beam trace becomes the
  symbolic log, and pruned candidates are listed with their rejection reason.
- **Honest degradation:** a missing checkpoint, a broken file, or `ML_ENABLED=false` drops the run to
  the Phase 2 heuristic recommender and says so in the UI — startup never fails because of the model.
- **Apply / revert:** the recommendation card builds the candidate index in the disposable shadow DB
  (measured with `EXPLAIN (ANALYZE)`) and drops it on revert. No DDL ever touches the target database.
- **Streaming Copilot:** `/ws/copilot/{run_id}` streams a grounded, deterministic explanation over a
  WebSocket in 3-character chunks at ~20 ms per character, preceded by a `thinking` pause and one
  collapsible `[tool] → result` chip per tool frame. No external LLM, no query text leaving the
  machine.
- **Durable runs:** when `METADATA_DB_DSN` is set, `analysis_runs` stores status, engine, error, and
  the full result JSON; without it, runs stay in memory exactly as in Phase 2.
- **Container-ready:** the API image is built from the repository root, installs CPU-only torch, and
  mounts `packages/ml-engine/weights` at runtime.

See `docs/phase-4-integration.md` for the bridge mapping, calibration notes, and verification log.

---

## Repository layout

```
DeepTune-DB/
├── apps/
│   ├── web/                  # Next.js 14 frontend (Phase 1 + Phase 4 wiring)
│   │   ├── src/app/          # App Router entry
│   │   ├── src/components/   # shell / left / center / right / ui
│   │   ├── src/lib/          # tokens, api client, plan adapter, mock fallback
│   │   ├── src/store/        # Zustand stores (session, analysis, copilot, graph)
│   │   └── src/types/        # strict shared types (graph + API contracts)
│   └── api/                  # FastAPI backend (Phase 2 + Phase 4 integration)
│       ├── src/api/          # v1 routes, engine status, copilot WebSocket
│       ├── src/core/         # config, errors, security, rate limits
│       ├── src/db/           # metadata, target, shadow, run archive
│       ├── src/services/     # sqlglot guard, EXPLAIN, DAG, engine bridge, pipeline
│       ├── src/schemas/      # strict Pydantic contracts
│       └── tests/            # 68 unit/contract tests
├── packages/
│   └── ml-engine/            # PyTorch/PyG engine (Phase 3)
│       ├── src/parsers/      # EXPLAIN JSON -> PyG graph
│       ├── src/models/       # 3-layer GATv2 + attention pooling
│       ├── src/search/       # symbolic pruning + beam search
│       ├── src/training/     # workload, datasets, metrics, CLIs
│       ├── src/inference.py  # PlanOptimizer facade for Phase 4
│       └── tests/            # 79 engine and boundary tests
├── infra/                    # Postgres init, hypopg shadow DB, nginx
├── docs/                     # phase records + docs/blueprints/ (source-of-truth specs)
├── docker-compose.yml        # metadata + target + shadow + api + web + nginx
├── AGENTS.md                 # Project constitution (boundaries + never-list)
├── .env.example              # Environment template (no secrets)
└── Makefile                  # install / dev / build / lint / api / ml / compose
```

Model weights live in `packages/ml-engine/weights/` and are git-ignored.

---

## Quick start

### Everything (Phase 4)

```bash
cp .env.example .env          # fill in JWT_SECRET and CREDENTIAL_ENCRYPTION_KEY
docker compose up -d --build  # metadata_db, target_db, shadow_db, api, web, nginx

cd apps/api
.venv/Scripts/python -m src.cli.token --subject dev   # mint a bearer token
```

> **Demo dataset limit:** keep the demo dataset under approximately **50 MB**. The shadow
> database is now disk-backed, but large datasets make `hypopg` validation and
> `EXPLAIN (ANALYZE)` slow during live demos.
>
> If you change `infra/postgres/demo.sql`, reset the shadow DB volume so PostgreSQL re-runs the
> init script:
>
> ```bash
> docker compose stop shadow_db
> docker compose rm -f shadow_db
> docker volume rm deeptune_shadow_data
> docker compose up -d shadow_db
> ```

The UI is at `http://localhost:3000` and the API at `http://localhost:8000`. For frontend hot
reload, stop the `web` service (`docker compose stop web`) and run `make dev` instead.

Open <http://localhost:3000>, paste the token into `localStorage["deeptune.token"]` (or set
`NEXT_PUBLIC_API_TOKEN`), then press `Ctrl+Enter` in the editor. The status bar shows
`GATv2 (neuro-symbolic)` when the engine loaded, or `heuristic fallback` with the reason in its
tooltip. Check <http://localhost:8000/api/v1/engine/status> for the same information as JSON.

The demo checkpoint is git-ignored, so train it first (see the ML engine section) or run with
`ML_ENABLED=false` to use the Phase 2 heuristic recommender.

### Frontend only

```bash
cd apps/web
npm install
npm run dev
```

Open <http://localhost:3000>. With the API down the console falls back to the sample plan.

```bash
npm run build       # production build
npm run lint        # ESLint (next/core-web-vitals)
npm run typecheck   # tsc --noEmit, strict mode
```

Requires Node 18.17+.

### Backend (Phase 2 + 4)

```bash
cd apps/api
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt
.venv/Scripts/python -m pip install -r requirements-ml.txt   # torch + PyG + onnxruntime (CPU)
.venv/Scripts/python -m pytest                                # 68 tests
.venv/Scripts/python -m uvicorn src.main:app --reload --port 8000
```

The API listens on <http://localhost:8000>, docs at <http://localhost:8000/docs>, and the nginx
proxy on <http://localhost:8080>. Requires Python 3.11+ and Docker Desktop for the database
containers. On POSIX use `.venv/bin/python` instead of `.venv/Scripts/python`.

### ML engine (Phase 3)

```bash
cd packages/ml-engine
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt
.venv/Scripts/python -m pytest                         # 79 tests
PYTHONPATH=src .venv/Scripts/python -m training.train \
  --epochs 120 --train-per-tier 1500 1700 1800 \
  --val-size 150 --test-size 200 --out weights/demo-final.pt
PYTHONPATH=src .venv/Scripts/python -m training.evaluate \
  --checkpoint weights/demo-final.pt --tier 3
PYTHONPATH=src .venv/Scripts/python -m training.export_onnx \
  --checkpoint weights/demo-final.pt --out weights/demo-final.onnx
```

The engine is CPU-only and does not need Docker. Training uses a deterministic synthetic EXPLAIN
workload: 5,000 TPC-H-like QEP graphs across three curriculum tiers. Phase 4 replaces it with real
`EXPLAIN (ANALYZE)` data and hypopg-modified plans. The root `Makefile` exposes the same flow as
`make ml-install`, `make ml-test`, `make ml-train` (20-epoch smoke recipe), `make ml-train-full`
(120-epoch shipped recipe), `make ml-eval`, and `make ml-export` (parity-gated ONNX export).

---

## Design system

Dark mode only. Tokens live in `apps/web/src/lib/tokens.ts` and
`apps/web/tailwind.config.ts`; components never hardcode a hex value.

| Token | Value | Role |
|---|---|---|
| `surface.0` | `#09090b` | App root |
| `surface.1` | `#0f172a` | Pane background |
| `surface.2` | `#18181b` | Cards |
| `surface.3` | `#27272a` | Elevated surfaces |
| `ai` | `#8b5cf6` | GNN attention / recommendation |
| `ok` | `#10b981` | Optimised |
| `warn` | `#eab308` | Mixed |
| `danger` | `#f97316` | Sequential scan / bottleneck |

Exactly four button variants are permitted: **Primary**, **Secondary**, **Ghost**, **Destructive**.

---

## Keyboard

| Shortcut | Action |
|---|---|
| `⌘K` / `Ctrl+K` | Command palette |
| `⌘↵` / `Ctrl+Enter` | Run & optimize |
| `Esc` | Close palette |

---

## Roadmap

All four planned phases are complete: the design system, the secured FastAPI backend, the
neuro-symbolic engine (ρ = 0.97 on held-out tier-3 plans), and the integration that connects them.

Natural next steps, none of which are required for the current scope:

- Collect a real `EXPLAIN (ANALYZE)` corpus to replace the synthetic training workload.
- Persist attention and explainability payloads so historical runs stay fully inspectable.
- Add an index-advisor view for workloads (many queries) rather than a single statement.

---

## License

Academic major-project work. All rights reserved by the author.
