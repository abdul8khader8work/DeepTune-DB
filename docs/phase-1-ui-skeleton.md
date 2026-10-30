# Phase 1 — UI Skeleton & Design System

**Status:** Complete
**Scope:** `apps/web/` only. No backend, no ML engine, no network calls.
**Source of truth:** `docs/blueprints/GOD_FILE.docx`, `docs/blueprints/MASTER_EXECUTION_PLAN.md.docx`,
`docs/blueprints/REVIEWER&Enforcer.docx`, `docs/blueprints/ui_interface.docx`,
`docs/blueprints/buttons_interface.docx`.

## Deliverables

### 1. Project bootstrapped

Next.js 14 (App Router), TypeScript strict, Tailwind CSS, shadcn-style primitives, React Flow,
Monaco, Framer Motion, cmdk, sonner, Zustand. (TanStack Query was removed in Patch 2 — it had no
imports.)

### 2. Global chrome

- **Topbar (48px):** brand, live connection pill, breadcrumbs, `⌘K` hint, settings, avatar.
- **Statusbar (32px):** GNN model, hypopg state, latency, node count, version, build hash.
- **Command palette:** `⌘K` / `Ctrl+K`, grouped actions, keyboard navigable.

### 3. Three-pane layout (25 / 50 / 25)

| Pane | Contents |
|---|---|
| Left | Monaco SQL editor, query tabs, format/clear, `Explain Only`, `Run & Optimize`, schema explorer with search |
| Center | React Flow QEP DAG, plan toggle, heatmap switch, zoom/fit/lock toolbar, time-travel slider |
| Right | Hero metrics, recommendation card, Copilot chat shell |

Panes are resizable via `react-resizable-panels`; each pane scrolls internally, the root does not.

### 4. Design system

- Tokens in `src/lib/tokens.ts` and `tailwind.config.ts` — no hex values in JSX.
- Exactly four button variants, defined once in `src/components/ui/button.tsx`.
- Inter (sans) + JetBrains Mono (mono) via `next/font`; all metrics use tabular numerals.
- Semantic accents only: `ai` for attention, `ok` for optimised, `danger` for bottlenecks.

### 5. Dummy data layer

- 7-node PostgreSQL-style plan with realistic costs, rows, selectivity, and attention scores.
- Animated high-cardinality edges (>10k rows).
- Time-travel slider drives the node colour morph and metric interpolation locally.
  (Patch 3 moved that interpolation onto a Framer Motion value — see
  `docs/phase-4-integration.md` §6.1.)

## Reviewer checklist

- [x] No `any` — strict interfaces in `src/types/`.
- [x] No hardcoded hex in JSX — tokens/utility classes only.
- [x] No pure black, no light surfaces.
- [x] No root-level scroll — `overflow-hidden` shell, `ScrollArea` per pane.
- [x] Four button variants only.
- [x] Topbar 48px, statusbar 32px, panes 25/50/25.
- [x] `QONode` 200px wide, 28px header, 4-column metrics, selectivity colour coding.
- [x] Edges `smoothstep`, 1.5px, `#3f3f46`; high-cardinality edges animated.
- [x] Every component under 200 lines.
- [x] No imports from `torch`, `numpy`, `pandas`, or the ML engine.
- [x] No backend calls; Phase 2 starts from a clean boundary.

## Final verification

Run from `apps/web/`:

| Command | Result |
|---|---|
| `npm run typecheck` | Pass — no errors |
| `npm run lint` | Pass — no warnings or errors |
| `npm run build` | Pass — static `/` route, 240 kB first load JS |

Manually exercised at 912 × 670: current → optimized toggle, GNN heatmap switch, time-travel
play/scrub, node selection, schema filter + token insert, command palette, toasts, and pane resize.
No console errors; no clipped panes.

## Deferred to later phases (intentionally)

- Real `EXPLAIN` data, backend validation, hypopg, WebSocket streaming.
- GNN attention values are mock data until Phase 3.
- Copilot replies are canned; Vercel AI SDK streaming arrives in Phase 4.
- `apps/api/`, `packages/ml-engine/`, `infra/`, `docker-compose.yml` are not created in Phase 1.
