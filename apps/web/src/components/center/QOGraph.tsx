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
import { planEdges, planNodes } from "@/lib/mock-plan";
import { useGraphStore } from "@/store/useGraphStore";
import type { QONodeData } from "@/types/graph";

const nodeTypes = { qo: QONode };
const edgeTypes = { qo: QOEdge };

const optimizedOverrides: Record<string, Partial<QONodeData>> = {
  seq: {
    op: "Index Scan",
    kind: "index",
    cost: 48,
    rows: 12000,
    selectivity: 0.04,
    attention: 0.18,
    bottleneck: false,
  },
  join: { cost: 860, attention: 0.32, bottleneck: false },
  aggregate: { cost: 980, attention: 0.2 },
  limit: { cost: 1000, attention: 0.12 },
};

export function QOGraph() {
  const view = useGraphStore((state) => state.view);
  const sliderT = useGraphStore((state) => state.sliderT);
  const locked = useGraphStore((state) => state.locked);
  const selectedNodeId = useGraphStore((state) => state.selectedNodeId);
  const setSelectedNode = useGraphStore((state) => state.setSelectedNode);
  const { fitView } = useReactFlow();

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      void fitView({ padding: 0.18 });
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
  }, [fitView]);

  const optimized = view === "optimized" || sliderT >= 0.5;

  const nodes = useMemo<Node[]>(() => {
    return planNodes.map((node) => {
      const override = optimized ? optimizedOverrides[node.id] : undefined;

      if (override) {
        return {
          ...node,
          selected: node.id === selectedNodeId,
          data: { ...node.data, ...override },
        };
      }

      return { ...node, selected: node.id === selectedNodeId };
    });
  }, [optimized, selectedNodeId]);

  const edges = useMemo(() => {
    return planEdges.map((edge) => {
      if (edge.id !== "e-seq-join" || !optimized) return edge;
      return {
        ...edge,
        data: {
          rows: 12000,
          bottleneck: false,
        },
      };
    });
  }, [optimized]);

  const onNodeClick = useCallback(
    (_event: React.MouseEvent, node: Node) => setSelectedNode(node.id),
    [setSelectedNode],
  );

  const onPaneClick = useCallback(
    () => setSelectedNode(null),
    [setSelectedNode],
  );

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      edgeTypes={edgeTypes}
      onNodeClick={onNodeClick}
      onPaneClick={onPaneClick}
      fitView
      fitViewOptions={{ padding: 0.18 }}
      minZoom={0.3}
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
