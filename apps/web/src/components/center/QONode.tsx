"use client";

import { Handle, Position, type NodeProps } from "@xyflow/react";
import {
  GitMerge,
  Hash,
  Layers,
  ScanLine,
  Search,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { formatCompact } from "@/lib/utils";
import type { QONodeModel } from "@/types/graph";
import { useGraphStore } from "@/store/useGraphStore";

const kindIcon: Record<string, LucideIcon> = {
  scan: ScanLine,
  index: Search,
  join: GitMerge,
  aggregate: Layers,
  hash: Hash,
};

function selectivityTone(selectivity: number): string {
  if (selectivity < 0.05) return "text-ok";
  if (selectivity <= 0.5) return "text-warn";
  return "text-danger";
}

export function QONode({ data, selected }: NodeProps<QONodeModel>) {
  const heatmap = useGraphStore((state) => state.heatmap);
  const Icon = kindIcon[data.kind] ?? Layers;

  const hot = heatmap && data.attention >= 0.75;
  const warm = heatmap && data.attention >= 0.5;

  const borderTone =
    data.bottleneck || data.selectivity > 0.5
      ? "border-danger/60"
      : data.selectivity < 0.05
        ? "border-ok/40"
        : "border-strong/70";

  const glow = hot
    ? "shadow-glow-danger"
    : warm
      ? "shadow-glow-ai"
      : "shadow-none";

  return (
    <div
      aria-label={`${data.op} on ${data.relation}, cost ${data.cost}, rows ${data.rows}, selectivity ${data.selectivity}`}
      className={cn(
        "w-[200px] min-h-[84px] overflow-hidden rounded-md border bg-surface-2 transition-all duration-300",
        borderTone,
        glow,
        selected && "ring-2 ring-ai ring-offset-2 ring-offset-surface-0",
      )}
    >
      <Handle type="target" position={Position.Bottom} />

      <div className="flex h-7 items-center justify-between gap-2 border-b border-subtle bg-surface-3 px-2">
        <span className="flex min-w-0 items-center gap-1.5">
          <Icon className="h-3 w-3 shrink-0 text-content-secondary" aria-hidden />
          <span className="truncate text-[11px] font-semibold text-content-primary">
            {data.op}
          </span>
        </span>
        <span className="shrink-0 font-mono text-[10px] text-content-tertiary">
          {data.relation}
        </span>
      </div>

      <div className="grid min-h-[56px] grid-cols-4">
        <Metric label="Cost" value={formatCompact(data.cost)} tone={data.bottleneck ? "text-danger" : "text-content-secondary"} />
        <Metric label="Rows" value={formatCompact(data.rows)} tone="text-content-secondary" />
        <Metric label="Sel" value={data.selectivity < 0.01 ? data.selectivity.toFixed(3) : data.selectivity.toFixed(2)} tone={selectivityTone(data.selectivity)} />
        <Metric label="Attn" value={`${Math.round(data.attention * 100)}%`} tone={hot ? "text-danger" : "text-ai"} />
      </div>

      <Handle type="source" position={Position.Top} />
    </div>
  );
}

type MetricProps = {
  label: string;
  value: string;
  tone: string;
};

function Metric({ label, value, tone }: MetricProps) {
  return (
    <div className="border-l border-subtle px-1.5 py-1.5 first:border-l-0">
      <div className="text-[9px] uppercase tracking-[0.06em] text-content-disabled">
        {label}
      </div>
      <div
        className={cn(
          "truncate font-mono text-[11px] tabular-nums",
          tone,
        )}
        title={value}
      >
        {value}
      </div>
    </div>
  );
}
