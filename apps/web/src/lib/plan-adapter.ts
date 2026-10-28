/**
 * Adapter: API DAG payload -> React Flow graph.
 *
 * The API emits `edges` as parent -> child (the way `build_dag` walks the plan).
 * `QONode` renders its source handle at the top and its target handle at the
 * bottom, so edges are flipped here to child -> parent: data flows upward from
 * the scans to the root operator, which is how a query plan is read.
 */

import type { AnalysisResult, DAGEdge, DAGNode } from "@/types/api";
import type { PlanNodeKind, QOEdgeModel, QONodeModel } from "@/types/graph";

const X_GAP = 236;
const Y_GAP = 132;

const INDEX_OPERATORS = new Set([
  "Index Scan",
  "Index Only Scan",
  "Bitmap Index Scan",
  "Tid Scan",
]);

const SCAN_OPERATORS = new Set([
  "Seq Scan",
  "Bitmap Heap Scan",
  "Foreign Scan",
  "Function Scan",
  "Values Scan",
  "CTE Scan",
  "Subquery Scan",
  "Append",
  "Gather",
  "Gather Merge",
]);

const JOIN_OPERATORS = new Set(["Hash Join", "Nested Loop", "Merge Join"]);

const HASH_OPERATORS = new Set(["Hash", "Memoize", "Materialize"]);

export function kindOf(operator: string): PlanNodeKind {
  if (INDEX_OPERATORS.has(operator)) return "index";
  if (SCAN_OPERATORS.has(operator)) return "scan";
  if (JOIN_OPERATORS.has(operator)) return "join";
  if (HASH_OPERATORS.has(operator)) return "hash";
  return "aggregate";
}

function depthsOf(nodes: DAGNode[], edges: DAGEdge[]): Map<string, number> {
  const children = new Map<string, string[]>();
  const isChild = new Set<string>();

  for (const edge of edges) {
    const siblings = children.get(edge.source) ?? [];
    siblings.push(edge.target);
    children.set(edge.source, siblings);
    isChild.add(edge.target);
  }

  const depth = new Map<string, number>();
  const queue: string[] = [];

  for (const node of nodes) {
    if (!isChild.has(node.id)) {
      depth.set(node.id, 0);
      queue.push(node.id);
    }
  }
  const root = nodes[0];
  if (queue.length === 0 && root !== undefined) {
    depth.set(root.id, 0);
    queue.push(root.id);
  }

  while (queue.length > 0) {
    const current = queue.shift() as string;
    const next = (depth.get(current) ?? 0) + 1;
    for (const child of children.get(current) ?? []) {
      if (!depth.has(child)) {
        depth.set(child, next);
        queue.push(child);
      }
    }
  }

  return depth;
}

export interface PlanView {
  nodes: QONodeModel[];
  edges: QOEdgeModel[];
  maxCost: number;
  maxRows: number;
}

export function toFlow(nodes: DAGNode[], edges: DAGEdge[]): PlanView {
  const depth = depthsOf(nodes, edges);
  const layers = new Map<number, DAGNode[]>();

  for (const node of nodes) {
    const level = depth.get(node.id) ?? 0;
    const bucket = layers.get(level) ?? [];
    bucket.push(node);
    layers.set(level, bucket);
  }

  const maxCost = nodes.reduce((peak, node) => Math.max(peak, node.estimated_cost), 0);
  const maxRows = nodes.reduce((peak, node) => Math.max(peak, node.estimated_rows), 0);
  const widest = Math.max(...[...layers.values()].map((layer) => layer.length), 1);
  const centre = ((widest - 1) / 2) * X_GAP;

  const attentionById = new Map(nodes.map((node) => [node.id, node.gnn_attention_score]));

  const flowNodes: QONodeModel[] = nodes.map((node) => {
    const level = depth.get(node.id) ?? 0;
    const layer = layers.get(level) ?? [node];
    const position = layer.findIndex((item) => item.id === node.id);

    return {
      id: node.id,
      type: "qo",
      position: {
        x: centre + (position - (layer.length - 1) / 2) * X_GAP,
        y: level * Y_GAP,
      },
      data: {
        op: node.operation_type,
        relation: node.relation_name ?? "",
        cost: node.estimated_cost,
        rows: node.estimated_rows,
        selectivity: maxRows > 0 ? node.estimated_rows / maxRows : 0,
        attention: node.gnn_attention_score,
        kind: kindOf(node.operation_type),
        bottleneck:
          node.gnn_attention_score >= 0.6 ||
          (maxCost > 0 && node.estimated_cost >= maxCost * 0.9),
      },
    };
  });

  const flowEdges: QOEdgeModel[] = edges.map((edge) => ({
    id: edge.id,
    source: edge.target,
    target: edge.source,
    type: "qo",
    data: {
      rows: edge.rows_transferred,
      bottleneck: (attentionById.get(edge.target) ?? 0) >= 0.6,
    },
  }));

  return { nodes: flowNodes, edges: flowEdges, maxCost, maxRows };
}

export interface HeroMetrics {
  beforeMs: number;
  afterMs: number;
  reductionPct: number;
  confidencePct: number;
  speedup: number;
  nodeCount: number;
  edgeCount: number;
}

export function heroMetrics(result: AnalysisResult): HeroMetrics {
  const before = result.original_metrics.time_ms ?? 0;
  const after = result.optimized_metrics.time_ms ?? 0;
  const reduction = before > 0 ? Math.max(0, ((before - after) / before) * 100) : 0;
  const confidence = result.recommendations.reduce(
    (peak, item) => Math.max(peak, item.confidence_score),
    0,
  );

  return {
    beforeMs: before,
    afterMs: after,
    reductionPct: Math.round(reduction * 10) / 10,
    confidencePct: Math.round(confidence * 100),
    speedup: result.speedup_factor,
    nodeCount: result.optimized_dag.length,
    edgeCount: result.edges.length,
  };
}
