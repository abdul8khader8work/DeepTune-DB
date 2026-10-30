import type { Edge, Node } from "@xyflow/react";

export type PlanNodeKind = "aggregate" | "join" | "scan" | "index" | "hash";

export type PlanView = "current" | "optimized";

/** Everything a node card renders; the original and optimized plans share it. */
export type QONodeMetrics = {
  op: string;
  relation: string;
  cost: number;
  rows: number;
  selectivity: number;
  attention: number;
  kind: PlanNodeKind;
  bottleneck: boolean;
};

export type QONodeData = QONodeMetrics & {
  /**
   * The optimized plan's node with the same id, when one exists.
   *
   * Patch 3 keeps the React Flow nodes stable while the time-travel slider
   * moves: the node itself stays the original one and the card interpolates
   * towards `counterpart` on a Framer Motion value. Without a counterpart (no
   * analysis yet, or the optimized view) the card simply does not morph.
   */
  counterpart?: QONodeMetrics;
};

export type QONodeModel = Node<QONodeData, "qo">;

export type QOEdgeData = {
  rows: number;
  bottleneck: boolean;
};

export type QOEdgeModel = Edge<QOEdgeData, "qo">;

export type ChatRole = "user" | "assistant";

export type ToolCallStatus = "running" | "done" | "error";

export type ToolCall = {
  tool: string;
  args: string;
  result: string;
  status: ToolCallStatus;
};

export type ChatMessage = {
  id: string;
  role: ChatRole;
  text: string;
  /** Every tool frame becomes its own chip, in arrival order. */
  tools?: ToolCall[];
};
