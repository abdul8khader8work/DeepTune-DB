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
| **4. Integration & Wow Factor** | Live DAG, real metrics, hypopg apply, streaming Copilot | **Complete** |

All four phases are complete. The web console now runs against the live API and the trained engine:
`Run & Optimize` executes a real `EXPLAIN`, the GNN ranks index configurations, hypopg validates the
winner, and the copilot streams an explanation of the result.

---

## What is in Phase 1

- **3-pane command center** at 25% / 50% / 25%, resizable, with a 48px topbar and 32px statusbar.
- **Left — Control Tower:** Monaco SQL editor with tab chrome, format/clear actions, `Explain Only`
  and `Run & Optimize`, plus a searchable schema explorer.
- **Center — Visual Brain:** interactive React Flow DAG with custom `QONode` cards (cost, rows,
  selectivity, GNN attention), animated high-cardinality edges, zoom/fit/lock toolbar, plan toggle,
  heatmap switch, and a working time-travel slider with play/pause and speed control.
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
- **EXPLAIN sandbox:** `EXPLAIN (ANALYZE, FORMAT JSON)` runs inside a transaction with a 5s
  `statement_timeout` and an unconditional rollback.
- **SQL guard:** `sqlglot` AST parsing rejects anything that is not exactly one read-only `SELECT`.
  No regex sanitising anywhere.
- **hypopg shadow DB:** hypothetical indexes are validated in a `tmpfs`-backed PostgreSQL 16
  container, then emitted as reviewable `CREATE INDEX CONCURRENTLY` scripts.
- **Security:** HS256 bearer tokens minted by `python -m src.cli.token`, Fernet-encrypted DSNs at
  rest, CORS locked to `http://localhost:3000`, and a per-IP rate limit on `/queries/analyze`.
- **Infrastructure:** `docker-compose.yml` runs metadata, target, shadow, API, and nginx services
  with health checks and loopback-only ports.

See `docs/phase-2-backend-api.md` for the endpoint table and reviewer checklist.

---

## What is in Phase 3

- **Plan parser:** PostgreSQL `EXPLAIN (FORMAT JSON)` becomes a PyG graph with operator one-hot
  features, log-scaled rows/cost/size, selectivity, edge cardinality, and join-type embeddings.
- **GATv2 cost model:** exactly three layers (128 wide, heads 4 → 4 → 1), global attention pooling,
  and a 128 → 64 → 1 head. It predicts `log1p(execution_time_ms)` and exposes per-node attention.
- **Symbolic pruning:** boolean/JSONB/low-distinct columns, duplicate indexes, left-prefix
  violations, the 15% storage budget, and the 3-index write-heavy cap are enforced before the GNN.
- **Beam search:** width 5, at most 3 indexes, one per table, ranked by predicted latency with a
  5% tie-break on write amplification. Only `CREATE INDEX CONCURRENTLY` text is emitted.
- **Training:** Huber loss, AdamW, cosine warm restarts, edge dropout, and the 1–20 / 21–50 / 51+
  curriculum. Validation uses MAE, RMSE, Spearman ρ, and median Q-error — never accuracy.
- **Measured result:** held-out synthetic tier 3 plans reach **ρ = 0.93** (MAE 168 ms); every tier
  clears the ρ > 0.85 target. Weights stay git-ignored.

See `docs/phase-3-ml-engine.md` for the graph contract, pruning table, and full metrics.

---

## What is in Phase 4

- **One data path:** the console calls `POST /queries/analyze`, polls the run, and renders the
  returned DAG. The Phase 1 mock plan survives only as an offline fallback.
- **Engine loaded once:** `PlanOptimizer` is constructed in the FastAPI `lifespan` on a worker
  thread, never inside a route. `GET /engine/status` reports the loaded checkpoint, parameter count,
  device, and layer/head configuration.
- **Real explainability:** GATv2 attention becomes the node heatmap, the beam trace becomes the
  symbolic log, and pruned candidates are listed with their rejection reason.
- **Honest degradation:** a missing checkpoint, a broken file, or `ML_ENABLED=false` drops the run to
  the Phase 2 heuristic recommender and says so in the UI — startup never fails because of the model.
- **Apply / revert:** the recommendation card injects the hypothetical index into the shadow DB via
  hypopg, then reverts it. No DDL ever touches the target database.
- **Streaming Copilot:** `/ws/copilot/{run_id}` streams a grounded, deterministic explanation
  word-by-word over a WebSocket. No external LLM, no query text leaving the machine.
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
│       └── tests/            # 59 unit/contract tests
├── packages/
│   └── ml-engine/            # PyTorch/PyG engine (Phase 3)
│       ├── src/parsers/      # EXPLAIN JSON -> PyG graph
│       ├── src/models/       # 3-layer GATv2 + attention pooling
│       ├── src/search/       # symbolic pruning + beam search
│       ├── src/training/     # workload, datasets, metrics, CLIs
│       ├── src/inference.py  # PlanOptimizer facade for Phase 4
│       └── tests/            # 70 engine and boundary tests
├── infra/                    # Postgres init, hypopg shadow DB, nginx
├── docs/                     # Phase records and implementation notes
├── docker-compose.yml        # metadata + target + shadow + api + nginx
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
docker compose up -d --build  # metadata_db, target_db, shadow_db, api, nginx

cd apps/api
.venv/Scripts/python -m src.cli.token --subject dev   # mint a bearer token

cd ../../apps/web
npm install && npm run dev
```

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
.venv/Scripts/python -m pip install -r requirements-ml.txt   # torch + PyG (CPU)
.venv/Scripts/python -m pytest                                # 59 tests
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
.venv/Scripts/python -m pytest                         # 70 tests
PYTHONPATH=src .venv/Scripts/python -m training.train \
  --epochs 120 --train-per-tier 400 500 800 --out weights/demo-final.pt
PYTHONPATH=src .venv/Scripts/python -m training.evaluate \
  --checkpoint weights/demo-final.pt --tier 3
```

The engine is CPU-only and does not need Docker. Training uses a deterministic synthetic EXPLAIN
workload; Phase 4 replaces it with real `EXPLAIN (ANALYZE)` data and hypopg-modified plans. The
root `Makefile` exposes the same flow as `make ml-install`, `make ml-test`, `make ml-train`, and
`make ml-eval`.

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
neuro-symbolic engine (ρ = 0.93 on held-out tier-3 plans), and the integration that connects them.

Natural next steps, none of which are required for the current scope:

- Feed hypopg-modified plans back into the GNN instead of scoring the baseline graph.
- Collect a real `EXPLAIN (ANALYZE)` corpus to replace the synthetic training workload.
- Persist attention and explainability payloads so historical runs stay fully inspectable.
- Add an index-advisor view for workloads (many queries) rather than a single statement.

---

## License

Academic major-project work. All rights reserved by the author.
