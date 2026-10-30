# DeepTune — Agent Constitution

Project: A Lightweight, Neuro-Symbolic Query Optimizer and Index Recommender for Local Databases.

This file is the machine-readable summary of `docs/blueprints/GOD_FILE.docx`,
`docs/blueprints/MASTER_EXECUTION_PLAN.md.docx` and `docs/blueprints/REVIEWER&Enforcer.docx`.
Read it before touching any file.

## 1. Monorepo boundaries (non-negotiable)

```
apps/web/          Next.js 14 frontend (Phase 1)
apps/api/          FastAPI backend (Phase 2)
packages/ml-engine PyTorch / PyG core (Phase 3)
infra/             Postgres, hypopg, nginx, docker-compose (Phase 2)
docs/              Blueprint + phase records
```

- `apps/web` MUST NOT import `torch`, `numpy`, `pandas`, or `packages/ml-engine`.
- `apps/api` MUST NOT contain ML training logic; it imports the engine as an inference library.
- `packages/ml-engine` MUST NOT import `fastapi`, `uvicorn`, or `sqlalchemy`.
- Never create files in the repository root unless the blueprint explicitly allows it.

## 2. Phased execution

Execute in order and stop for approval after each phase.

1. **Phase 1 — UI Skeleton & Design System.** Only `apps/web/`. 3-pane layout, tokens, dummy React Flow graph.
2. **Phase 2 — Backend API & Security.** Only `apps/api/` and `infra/`.
3. **Phase 3 — Neuro-Symbolic ML Engine.** Only `packages/ml-engine/`.
4. **Phase 4 — Integration & Wow Factor.** Wire web → api → engine.

## 3. The NEVER list

- NEVER use `any` in TypeScript. Strict interfaces for every prop and API response.
- NEVER use inline styles for colour/layout tokens. Tailwind utilities only (dynamic geometry may use CSS custom properties).
- NEVER use pure black `#000000` or any light background.
- NEVER use blocking synchronous I/O in FastAPI. `async def` + `asyncpg` only.
- NEVER load the PyTorch model inside a route handler. Load once in `lifespan`.
- NEVER use regex to sanitise SQL. Use `sqlglot` AST parsing + transaction-wrapped `EXPLAIN`.
- NEVER execute `EXPLAIN (ANALYZE)` outside a transaction with `SET statement_timeout = '5000'` and rollback.
- NEVER auto-apply DDL to the Target DB. Emit `CREATE INDEX CONCURRENTLY` for user review.
- NEVER use "Accuracy" for the GNN regressor. Use MAE, RMSE, Spearman ρ.
- NEVER exceed 200 lines per React component file.
- NEVER commit `.env` files, credentials, or model weights.

## 4. Design tokens (single source of truth)

| Token | Value | Usage |
|---|---|---|
| `surface.0` | `#09090b` | App root |
| `surface.1` | `#0f172a` | Pane background |
| `surface.2` | `#18181b` | Cards / panels |
| `surface.3` | `#27272a` | Elevated surfaces |
| `border.default` | `#27272a` | Hairlines |
| `text.primary` | `#fafafa` | Headings |
| `text.secondary` | `#a1a1aa` | Body |
| `text.tertiary` | `#71717a` | Captions |
| `ai` | `#8b5cf6` | GNN attention / recommendations only |
| `ok` | `#10b981` | Optimised / low cost |
| `warn` | `#eab308` | Mixed |
| `danger` | `#f97316` | Sequential scan / bottleneck |
| `info` | `#06b6d4` | Telemetry |

Exactly four button variants: Primary, Secondary, Ghost, Destructive (see `apps/web/src/lib/tokens.ts`).
Topbar 48px, statusbar 32px, 3 panes at 25 / 50 / 25. Each pane scrolls internally; the root never scrolls.

## 5. Phase 1 status

Complete. See `docs/phase-1-ui-skeleton.md` for the enforced checklist.
