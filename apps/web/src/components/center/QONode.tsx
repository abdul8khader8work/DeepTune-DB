"use client";

import { Handle, Position, type NodeProps } from "@xyflow/react";
import { AnimatePresence, motion, useTransform, type Transition } from "framer-motion";
import {
  GitMerge,
  Hash,
  Layers,
  ScanLine,
  Search,
  type LucideIcon,
} from "lucide-react";
import { morphProgress } from "@/lib/morph";
import { Metric, MorphValue } from "@/components/center/QOMetric";
import { cn } from "@/lib/utils";
import { useGraphStore } from "@/store/useGraphStore";
import type { QONodeModel } from "@/types/graph";

const kindIcon: Record<string, LucideIcon> = {
  scan: ScanLine,
  index: Search,
  join: GitMerge,
  aggregate: Layers,
  hash: Hash,
};

//: Patch 3: tone wash and label swap are Framer tweens; the only CSS transition
//: left on the card is the border colour.
const TONE: Transition = { duration: 0.32, ease: "easeOut" };
const LAYOUT: Transition = { duration: 0.3, ease: "easeOut" };

function selectivityTone(selectivity: number): string {
  if (selectivity < 0.05) return "text-ok";
  if (selectivity <= 0.5) return "text-warn";
  return "text-danger";
}

export function QONode({ data, selected }: NodeProps<QONodeModel>) {
  const heatmap = useGraphStore((state) => state.heatmap);
  // The only React render during a scrub: the 50% identity flip. Everything
  // numeric in between is written to the DOM by `MorphValue`.
  const morphed = useGraphStore(
    (state) => state.view === "optimized" || state.sliderT >= 0.5,
  );

  const counterpart = data.counterpart;
  const shown = morphed && counterpart ? counterpart : data;
  const Icon = kindIcon[shown.kind] ?? Layers;

  // Danger wash fades out as the plan is optimized; the ok wash fades in.
  const dangerOpacity = useTransform(morphProgress, (t) =>
    data.bottleneck ? 1 - t : 0,
  );
  const okOpacity = useTransform(morphProgress, (t) =>
    counterpart && !counterpart.bottleneck ? t : 0,
  );

  const hot = heatmap && shown.attention >= 0.75;
  const warm = heatmap && shown.attention >= 0.5;

  const borderTone =
    shown.bottleneck || shown.selectivity > 0.5
      ? "border-danger/60"
      : shown.selectivity < 0.05
        ? "border-ok/40"
        : "border-strong/70";

  const glow = hot
    ? "shadow-glow-danger"
    : warm
      ? "shadow-glow-ai"
      : "shadow-none";

  return (
    <div
      aria-label={`${shown.op} on ${shown.relation}, cost ${Math.round(shown.cost)}, rows ${Math.round(shown.rows)}`}
      className="relative"
    >
      <Handle type="target" position={Position.Bottom} />

      {/* Only the inner content is a motion layout: React Flow owns the outer
          wrapper's absolute position and must keep measuring it unchanged. */}
      <motion.div
        layout
        transition={{ layout: LAYOUT }}
        className={cn(
          "relative w-[200px] min-h-[84px] overflow-hidden rounded-md border bg-surface-2 will-change-transform",
          "transition-colors duration-300",
          borderTone,
          glow,
          selected && "ring-2 ring-ai ring-offset-2 ring-offset-surface-0",
        )}
      >
        <motion.div
          aria-hidden
          style={{ opacity: dangerOpacity }}
          className="pointer-events-none absolute inset-0 bg-danger/10"
        />
        <motion.div
          aria-hidden
          style={{ opacity: okOpacity }}
          className="pointer-events-none absolute inset-0 bg-ok/10"
        />

        <div className="relative flex h-7 items-center justify-between gap-2 border-b border-subtle bg-surface-3 px-2">
          <span className="relative flex min-w-0 items-center gap-1.5 overflow-hidden">
            <Icon
              className="h-3 w-3 shrink-0 text-content-secondary"
              aria-hidden
            />
            <AnimatePresence initial={false} mode="popLayout">
              <motion.span
                key={shown.op}
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -6 }}
                transition={TONE}
                className="truncate text-[11px] font-semibold text-content-primary"
              >
                {shown.op}
              </motion.span>
            </AnimatePresence>
          </span>
          <span className="shrink-0 font-mono text-[10px] text-content-tertiary">
            {shown.relation}
          </span>
        </div>

        <div className="relative grid min-h-[56px] grid-cols-4">
          <Metric
            label="Cost"
            tone={shown.bottleneck ? "text-danger" : "text-content-secondary"}
          >
            <MorphValue
              kind="cost"
              from={data.cost}
              to={counterpart?.cost ?? data.cost}
            />
          </Metric>
          <Metric label="Rows" tone="text-content-secondary">
            <MorphValue
              kind="rows"
              from={data.rows}
              to={counterpart?.rows ?? data.rows}
            />
          </Metric>
          <Metric label="Sel" tone={selectivityTone(shown.selectivity)}>
            <MorphValue
              kind="selectivity"
              from={data.selectivity}
              to={counterpart?.selectivity ?? data.selectivity}
            />
          </Metric>
          <Metric label="Attn" tone={hot ? "text-danger" : "text-ai"}>
            <MorphValue
              kind="attention"
              from={data.attention}
              to={counterpart?.attention ?? data.attention}
            />
          </Metric>
        </div>
      </motion.div>

      <Handle type="source" position={Position.Top} />
    </div>
  );
}
