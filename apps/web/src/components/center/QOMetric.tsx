"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { lerp, morphProgress } from "@/lib/morph";
import { cn, formatCompact } from "@/lib/utils";

const FORMATTERS = {
  cost: (value: number) => formatCompact(value),
  rows: (value: number) => formatCompact(value),
  selectivity: (value: number) => (value < 0.01 ? value.toFixed(3) : value.toFixed(2)),
  attention: (value: number) => `${Math.round(value * 100)}%`,
} as const;

export type MetricKind = keyof typeof FORMATTERS;

type MetricProps = {
  label: string;
  tone: string;
  children: ReactNode;
};

/** One labelled readout cell in a `QONode` card. */
export function Metric({ label, tone, children }: MetricProps) {
  return (
    <div className="border-l border-subtle px-1.5 py-1.5 first:border-l-0">
      <div className="text-[9px] uppercase tracking-[0.06em] text-content-disabled">
        {label}
      </div>
      <div className={cn("truncate font-mono text-[11px] tabular-nums", tone)}>
        {children}
      </div>
    </div>
  );
}

type MorphValueProps = {
  kind: MetricKind;
  from: number;
  to: number;
};

/**
 * A readout driven by the morph motion value instead of React state.
 *
 * The node subscribes to `morphProgress` and writes the interpolated number
 * straight into `textContent`, so a 60 fps scrub costs one DOM write per metric
 * per frame and zero React renders.
 */
export function MorphValue({ kind, from, to }: MorphValueProps) {
  const ref = useRef<HTMLSpanElement>(null);
  const format = FORMATTERS[kind];

  useEffect(() => {
    const write = (t: number) => {
      if (ref.current) ref.current.textContent = format(lerp(from, to, t));
    };
    write(morphProgress.get());
    return morphProgress.on("change", write);
  }, [format, from, to]);

  return <span ref={ref}>{format(from)}</span>;
}
