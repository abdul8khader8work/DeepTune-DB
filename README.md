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
| 2. Backend API & Security | FastAPI, read-only role, `EXPLAIN` sandbox, `hypopg` shadow DB | Next |
| 3. Neuro-Symbolic ML Engine | JSON→PyG parser, GATv2, symbolic pruning, beam search | Planned |
| 4. Integration & Wow Factor | Live DAG, time-travel morph, streaming Copilot | Planned |

This repository currently contains **Phase 1 only**. The UI is fully interactive with realistic
dummy data, but it is not yet wired to a backend.

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

## Repository layout

```
DeepTune-DB/
├── apps/
│   └── web/                  # Next.js 14 frontend (Phase 1)
│       ├── src/app/          # App Router entry
│       ├── src/components/   # shell / left / center / right / ui
│       ├── src/lib/          # tokens, utils, mock data
│       ├── src/store/        # Zustand stores
│       └── src/types/        # strict shared types
├── docs/                     # Phase records and implementation notes
├── AGENTS.md                 # Project constitution (boundaries + never-list)
├── .env.example              # Environment template (no secrets)
└── Makefile                  # install / dev / build / lint
```

`apps/api/`, `packages/ml-engine/` and `infra/` are intentionally absent until their phase starts.

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

Phase 2 adds the FastAPI backend: least-privilege `query_optimizer` role, transaction-wrapped
`EXPLAIN (ANALYZE, FORMAT JSON)` with a 5s timeout and rollback, and `hypopg` validation in an
isolated shadow database. Phase 3 adds the GATv2 + beam-search engine. Phase 4 wires it all
together with streaming updates and the node-morph animation.

---

## License

Academic major-project work. All rights reserved by the author.
