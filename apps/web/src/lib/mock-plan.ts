import type { QOEdgeModel, QONodeModel } from "@/types/graph";

/**
 * Phase 1 mock query plan.
 *
 * Shaped like `EXPLAIN (ANALYZE, FORMAT JSON)` output flattened into a
 * bottom-up DAG: leaves are scans, the root is the Limit node. Phase 3 will
 * replace this file with the real JSON -> PyG parser output.
 */
export const planNodes: QONodeModel[] = [
  {
    id: "limit",
    type: "qo",
    position: { x: 320, y: 0 },
    data: {
      op: "Limit",
      relation: "orders",
      cost: 15240,
      rows: 20,
      selectivity: 0.0002,
      attention: 0.18,
      kind: "aggregate",
      bottleneck: false,
    },
  },
  {
    id: "aggregate",
    type: "qo",
    position: { x: 320, y: 118 },
    data: {
      op: "Aggregate",
      relation: "orders",
      cost: 15230,
      rows: 42,
      selectivity: 0.0004,
      attention: 0.36,
      kind: "aggregate",
      bottleneck: false,
    },
  },
  {
    id: "join",
    type: "qo",
    position: { x: 320, y: 246 },
    data: {
      op: "Hash Join",
      relation: "orders",
      cost: 12480,
      rows: 4210,
      selectivity: 0.12,
      attention: 0.88,
      kind: "join",
      bottleneck: true,
    },
  },
  {
    id: "seq",
    type: "qo",
    position: { x: 64, y: 386 },
    data: {
      op: "Seq Scan",
      relation: "orders",
      cost: 12450,
      rows: 100000,
      selectivity: 0.62,
      attention: 0.95,
      kind: "scan",
      bottleneck: true,
    },
  },
  {
    id: "hash",
    type: "qo",
    position: { x: 512, y: 386 },
    data: {
      op: "Hash",
      relation: "customers",
      cost: 320,
      rows: 12000,
      selectivity: 0.35,
      attention: 0.41,
      kind: "hash",
      bottleneck: false,
    },
  },
  {
    id: "idx",
    type: "qo",
    position: { x: 512, y: 514 },
    data: {
      op: "Index Scan",
      relation: "customers",
      cost: 45,
      rows: 12000,
      selectivity: 0.03,
      attention: 0.12,
      kind: "index",
      bottleneck: false,
    },
  },
  {
    id: "bitmap",
    type: "qo",
    position: { x: 512, y: 642 },
    data: {
      op: "Bitmap Index Scan",
      relation: "customers",
      cost: 18,
      rows: 12000,
      selectivity: 0.03,
      attention: 0.08,
      kind: "index",
      bottleneck: false,
    },
  },
];

/**
 * Phase 1 demo data: the same DAG after `idx_orders_customer_date` exists.
 *
 * The offline sample has no analysis behind it, so the time-travel slider would
 * have nothing to morph towards. These values are the shape the optimizer
 * reports for `initialQuery` once the recommended index is in place, matching
 * `planMetrics` (423 ms -> 53 ms). A live run always uses the API payload
 * instead; this is never mixed into real results.
 */
export const optimizedPlanNodes: QONodeModel[] = [
  {
    id: "limit",
    type: "qo",
    position: { x: 320, y: 0 },
    data: {
      op: "Limit",
      relation: "orders",
      cost: 1830,
      rows: 20,
      selectivity: 0.0002,
      attention: 0.12,
      kind: "aggregate",
      bottleneck: false,
    },
  },
  {
    id: "aggregate",
    type: "qo",
    position: { x: 320, y: 118 },
    data: {
      op: "Aggregate",
      relation: "orders",
      cost: 1780,
      rows: 42,
      selectivity: 0.0004,
      attention: 0.21,
      kind: "aggregate",
      bottleneck: false,
    },
  },
  {
    id: "join",
    type: "qo",
    position: { x: 320, y: 246 },
    data: {
      op: "Nested Loop",
      relation: "orders",
      cost: 1490,
      rows: 4210,
      selectivity: 0.12,
      attention: 0.34,
      kind: "join",
      bottleneck: false,
    },
  },
  {
    id: "seq",
    type: "qo",
    position: { x: 64, y: 386 },
    data: {
      op: "Index Scan",
      relation: "orders",
      cost: 1470,
      rows: 4210,
      selectivity: 0.042,
      attention: 0.46,
      kind: "index",
      bottleneck: false,
    },
  },
  {
    id: "hash",
    type: "qo",
    position: { x: 512, y: 386 },
    data: {
      op: "Memoize",
      relation: "customers",
      cost: 96,
      rows: 12000,
      selectivity: 0.35,
      attention: 0.22,
      kind: "hash",
      bottleneck: false,
    },
  },
  {
    id: "idx",
    type: "qo",
    position: { x: 512, y: 514 },
    data: {
      op: "Index Only Scan",
      relation: "customers",
      cost: 21,
      rows: 12000,
      selectivity: 0.03,
      attention: 0.08,
      kind: "index",
      bottleneck: false,
    },
  },
  {
    id: "bitmap",
    type: "qo",
    position: { x: 512, y: 642 },
    data: {
      op: "Index Scan",
      relation: "customers",
      cost: 9,
      rows: 12000,
      selectivity: 0.03,
      attention: 0.05,
      kind: "index",
      bottleneck: false,
    },
  },
];

export const planEdges: QOEdgeModel[] = [
  {
    id: "e-seq-join",
    source: "seq",
    target: "join",
    type: "qo",
    data: { rows: 100000, bottleneck: true },
  },
  {
    id: "e-hash-join",
    source: "hash",
    target: "join",
    type: "qo",
    data: { rows: 12000, bottleneck: false },
  },
  {
    id: "e-idx-hash",
    source: "idx",
    target: "hash",
    type: "qo",
    data: { rows: 12000, bottleneck: false },
  },
  {
    id: "e-bitmap-idx",
    source: "bitmap",
    target: "idx",
    type: "qo",
    data: { rows: 12000, bottleneck: false },
  },
  {
    id: "e-join-agg",
    source: "join",
    target: "aggregate",
    type: "qo",
    data: { rows: 4210, bottleneck: false },
  },
  {
    id: "e-agg-limit",
    source: "aggregate",
    target: "limit",
    type: "qo",
    data: { rows: 42, bottleneck: false },
  },
];

export const planMetrics = {
  beforeMs: 423,
  afterMs: 53,
  confidence: 94,
  reductionPct: 87.4,
  nodeCount: planNodes.length,
} as const;

export const recommendationSql = `CREATE INDEX CONCURRENTLY idx_orders_customer_date
  ON orders (customer_id, order_date DESC)
  INCLUDE (status, total)
  WHERE status = 'paid';`;

export const migrationSql = `-- DeepTune migration — review before applying
BEGIN;

CREATE INDEX CONCURRENTLY idx_orders_customer_date
  ON orders (customer_id, order_date DESC)
  INCLUDE (status, total)
  WHERE status = 'paid';

COMMIT;`;

export const initialQuery = `SELECT c.name,
       SUM(o.total) AS revenue
FROM orders o
JOIN customers c ON c.id = o.customer_id
WHERE o.order_date >= now() - interval '30 days'
  AND o.status = 'paid'
GROUP BY c.name
ORDER BY revenue DESC
LIMIT 20;`;
