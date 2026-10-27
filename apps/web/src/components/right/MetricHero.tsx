import { Sparkles, TrendingDown } from "lucide-react";
import { planMetrics } from "@/lib/mock-plan";
import { formatMs } from "@/lib/utils";

export function MetricHero() {
  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between">
        <span className="text-[10px] font-medium uppercase tracking-[0.08em] text-content-tertiary">
          Hero metrics
        </span>
        <span className="font-mono text-[10px] text-content-disabled">
          single query
        </span>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div className="rounded-md border border-subtle bg-surface-2 p-2 xl:p-3">
          <div className="text-[9px] uppercase tracking-[0.06em] text-content-tertiary">
            Original latency
          </div>
          <div className="mt-1 font-mono text-xl font-semibold leading-none tabular-nums text-danger xl:text-3xl">
            {formatMs(planMetrics.beforeMs)}
          </div>
        </div>

        <div className="rounded-md border border-ok/25 bg-surface-2 p-2 xl:p-3">
          <div className="text-[9px] uppercase tracking-[0.06em] text-content-tertiary">
            Optimized latency
          </div>
          <div className="mt-1 font-mono text-xl font-semibold leading-none tabular-nums text-ok xl:text-3xl">
            {formatMs(planMetrics.afterMs)}
          </div>
        </div>
      </div>

      <div className="mt-1.5 flex items-center justify-between">
        <span className="flex items-center gap-1 text-[11px] font-medium text-ok">
          <TrendingDown className="h-3 w-3" aria-hidden />
          {planMetrics.reductionPct}% reduction
        </span>
        <span className="flex items-center gap-1 font-mono text-[10px] text-content-tertiary">
          <Sparkles className="h-2.5 w-2.5 text-ai" aria-hidden />
          GATv2 · v1.2
        </span>
      </div>
    </div>
  );
}
