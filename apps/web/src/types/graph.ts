import type { Edge, Node } from "@xyflow/react";

export type PlanNodeKind = "aggregate" | "join" | "scan" | "index" | "hash";

export type PlanView = "current" | "optimized";

export type QONodeData = {
  op: string;
  relation: string;
  cost: number;
  rows: number;
  selectivity: number;
  attention: number;
  kind: PlanNodeKind;
  bottleneck: boolean;
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
