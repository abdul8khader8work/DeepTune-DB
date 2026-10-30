"use client";

import { useCallback, useEffect, useMemo } from "react";
import {
  Background,
  BackgroundVariant,
  ReactFlow,
  useReactFlow,
  type Node,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { QONode } from "@/components/center/QONode";
import { QOEdge } from "@/components/center/QOEdge";
import { optimizedPlanNodes, planEdges, planNodes } from "@/lib/mock-plan";
import { morphProgress } from "@/lib/morph";
import { toFlow, type PlanView } from "@/lib/plan-adapter";
import { useAnalysisStore } from "@/store/useAnalysisStore";
import { useGraphStore } from "@/store/useGraphStore";
import type { QONodeMetrics } from "@/types/graph";

const nodeTypes = { qo: QONode };
const edgeTypes = { qo: QOEdge };

const samplePlan: PlanView = {
  nodes: planNodes,
  edges: planEdges,
  maxCost: 0,
  maxRows: 0,
};

//: Offline fallback: the same demo DAG with the recommended index applied, so
//: the time-travel slider still has a counterpart to morph towards before the
//: first analysis. See `optimizedPlanNodes` in lib/mock-plan.ts.
const sampleOptimized: PlanView = {
  nodes: optimizedPlanNodes,
  edges: planEdges,
  maxCost: 0,
  maxRows: 0,
};

const EMPTY: ReadonlyMap<string, QONodeMetrics> = new Map();

export function QOGraph() {
  const result = useAnalysisStore((state) => state.result);
  const view = useGraphStore((state) => state.view);
  const locked = useGraphStore((state) => state.locked);
  const selectedNodeId = useGraphStore((state) => state.selectedNodeId);
  const setSelectedNode = useGraphStore((state) => state.setSelectedNode);
  const { fitView } = useReactFlow();

  const original = useMemo<PlanView>(() => {
    if (!result) return samplePlan;
    const edges =
      result.original_edges.length > 0 ? result.original_edges : result.edges;
    return toFlow(result.original_dag, edges);
  }, [result]);

  const optimized = useMemo<PlanView>(() => {
    if (!result) return sampleOptimized;
    return toFlow(result.optimized_dag, result.edges);
  }, [result]);

  // Patch 3: the graph renders ONE plan and never rebuilds while the slider
  // moves. Each node carries the optimized node with the same id, and the card
  // interpolates towards it on a motion value (see lib/morph.ts).
  const plan = view === "optimized" ? optimized : original;

  const counterparts = useMemo<ReadonlyMap<string, QONodeMetrics>>(() => {
    if (view === "optimized") return EMPTY;
    return new Map(optimized.nodes.map((node) => [node.id, node.data]));
  }, [optimized.nodes, view]);

  // Slider -> motion value. Subscribed imperatively so scrubbing re-renders
  // neither this component nor React Flow; only the node cards react.
  useEffect(() => {
    const sync = () => {
      const state = useGraphStore.getState();
      morphProgress.set(state.view === "optimized" ? 1 : state.sliderT);
    };
    sync();
    return useGraphStore.subscribe(sync);
  }, []);

  const nodeCount = plan.nodes.length;

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      void fitView({ padding: 0.18, duration: 320 });
    });

    const element = document.querySelector(".react-flow");
    const observer = element
      ? new ResizeObserver(() => {
          void fitView({ padding: 0.18 });
        })
      : null;

    if (element && observer) observer.observe(element);

    return () => {
      window.cancelAnimationFrame(frame);
      observer?.disconnect();
    };
  }, [fitView, nodeCount, view]);

  const nodes = useMemo<Node[]>(
    () =>
      plan.nodes.map((node) => ({
        ...node,
        data: { ...node.data, counterpart: counterparts.get(node.id) },
        selected: node.id === selectedNodeId,
      })),
    [counterparts, plan.nodes, selectedNodeId],
  );

  const onNodeClick = useCallback(
    (_event: React.MouseEvent, node: Node) => setSelectedNode(node.id),
    [setSelectedNode],
  );

  const onPaneClick = useCallback(() => setSelectedNode(null), [setSelectedNode]);

  if (nodeCount === 0) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-[11px] text-content-tertiary">
          No plan yet. Run a query to capture its execution plan.
        </p>
      </div>
    );
  }

  return (
    <ReactFlow
      nodes={nodes}
      edges={plan.edges}
      nodeTypes={nodeTypes}
      edgeTypes={edgeTypes}
      onNodeClick={onNodeClick}
      onPaneClick={onPaneClick}
      fitView
      fitViewOptions={{ padding: 0.18 }}
      minZoom={0.2}
      maxZoom={1.5}
      nodesDraggable={!locked}
      nodesConnectable={false}
      elementsSelectable
      panOnScroll
      proOptions={{ hideAttribution: true }}
      className="h-full w-full"
      aria-label="Interactive query execution plan graph"
    >
      <Background
        variant={BackgroundVariant.Dots}
        gap={24}
        size={1}
        color="var(--border-subtle)"
      />
    </ReactFlow>
  );
}
