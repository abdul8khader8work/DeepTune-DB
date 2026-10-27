"use client";

import {
  BaseEdge,
  getSmoothStepPath,
  type EdgeProps,
} from "@xyflow/react";
import { cn } from "@/lib/utils";
import type { QOEdgeModel } from "@/types/graph";

export function QOEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  data,
}: EdgeProps<QOEdgeModel>) {
  const [path] = getSmoothStepPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
    borderRadius: 8,
  });

  const rows = data?.rows ?? 0;
  const tone = data?.bottleneck
    ? "bottleneck"
    : rows > 10000
      ? "highcard"
      : "default";

  return (
    <BaseEdge
      id={id}
      path={path}
      className={cn("qo-edge", `qo-edge--${tone}`)}
    />
  );
}
