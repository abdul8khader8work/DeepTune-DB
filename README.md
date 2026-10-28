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
| 3. Neuro-Symbolic ML Engine | JSON→PyG parser, GATv2, symbolic pruning, beam search | Next |
| 4. Integration & Wow Factor | Live DAG, time-travel morph, streaming Copilot | Planned |

Phases 1 and 2 are complete. The UI is fully interactive with realistic dummy data and the API is
ready, but the two are not wired together until Phase 4.

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

## Repository layout

```
DeepTune-DB/
├── apps/
│   ├── web/                  # Next.js 14 frontend (Phase 1)
│   │   ├── src/app/          # App Router entry
│   │   ├── src/components/   # shell / left / center / right / ui
│   │   ├── src/lib/          # tokens, utils, mock data
│   │   ├── src/store/        # Zustand stores
│   │   └── src/types/        # strict shared types
│   └── api/                  # FastAPI backend (Phase 2)
│       ├── src/api/          # v1 routes + legacy aliases
│       ├── src/core/         # config, errors, security, rate limits
│       ├── src/db/           # metadata, target, shadow connections
│       ├── src/services/     # sqlglot guard, EXPLAIN, DAG, candidates
│       ├── src/schemas/      # strict Pydantic contracts
│       └── tests/            # 40 unit/contract tests
├── infra/                    # Postgres init, hypopg shadow DB, nginx
├── docs/                     # Phase records and implementation notes
├── docker-compose.yml        # metadata + target + shadow + api + nginx
├── AGENTS.md                 # Project constitution (boundaries + never-list)
├── .env.example              # Environment template (no secrets)
└── Makefile                  # install / dev / build / lint / api / compose
```

`packages/ml-engine/` is intentionally absent until Phase 3.

---

## Quick start

```bash
cd apps/web
npm install
npm run dev
```

Open <http://localhost:3000>.

```bash
npm run build       # production build
npm run lint        # ESLint (next/core-web-vitals)
npm run typecheck   # tsc --noEmit, strict mode
```

Requires Node 18.17+.

### Backend (Phase 2)

```bash
cp .env.example .env          # fill in JWT_SECRET and CREDENTIAL_ENCRYPTION_KEY
docker compose up -d --build  # metadata_db, target_db, shadow_db, api, nginx

cd apps/api
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt
.venv/Scripts/python -m pytest
.venv/Scripts/python -m src.cli.token --subject dev   # bearer token
```

The API listens on <http://localhost:8000>, docs at <http://localhost:8000/docs>, and the nginx
proxy on <http://localhost:8080>. Requires Python 3.11+ and Docker Desktop for the database
containers. On POSIX use `.venv/bin/python` instead of `.venv/Scripts/python`.

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

Phase 2 (complete) added the FastAPI backend: least-privilege `query_optimizer` role,
transaction-wrapped `EXPLAIN (ANALYZE, FORMAT JSON)` with a 5s timeout and rollback, `hypopg`
validation in a `tmpfs` shadow database, encrypted DSNs, JWT auth, and a rate-limited analysis
pipeline. Phase 3 adds the GATv2 + beam-search engine. Phase 4 wires the web app to the API with
streaming updates and the node-morph animation.

---

## License

Academic major-project work. All rights reserved by the author.
