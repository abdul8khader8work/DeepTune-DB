"use client";

import { planEdges, planMetrics } from "@/lib/mock-plan";
import { formatMs } from "@/lib/utils";
import { useAnalysisStore } from "@/store/useAnalysisStore";
import { useSessionStore } from "@/store/useSessionStore";

const buildHash = "8a9f2c";

export function StatusBar() {
  const engine = useSessionStore((state) => state.engine);
  const health = useSessionStore((state) => state.health);
  const result = useAnalysisStore((state) => state.result);

  const backend = engine?.backend ?? "gnn";
  const version = engine?.model_version ?? "v1.0";
  const runtime = engine?.runtime ?? "heuristic";
  const online = engine?.available ?? false;
  const hypopg = health?.shadow_db_configured ?? true;

  const latency = result?.optimized_metrics.time_ms;
  const nodes = result?.optimized_dag.length ?? planMetrics.nodeCount;
  const edges = result?.edges.length ?? planEdges.length;

  return (
    <footer className="flex h-8 shrink-0 items-center justify-between border-t border-subtle bg-surface-0 px-4 text-[11px] text-content-tertiary">
      <div className="flex items-center gap-3">
        <span className="flex items-center gap-1.5">
          <span
            className={
              backend === "gnn"
                ? "h-1 w-1 rounded-full bg-ai"
                : "h-1 w-1 rounded-full bg-warn"
            }
            aria-hidden
          />
          {backend === "gnn" ? "GNN Model:" : "Fallback:"}{" "}
          <span className="font-mono text-content-secondary">{version}</span>
          <span className={online ? "text-ok" : "text-warn"}>
            ({online ? "Active" : "Heuristic"})
          </span>
          <span
            className="rounded-sm border border-info/30 px-1 font-mono text-[9px] uppercase tracking-[0.06em] text-info"
            title="Inference runtime reported by GET /api/v1/engine/status"
          >
            {runtime}
          </span>
        </span>
        <span className="hidden h-3 w-px bg-surface-3 sm:block" aria-hidden />
        <span className="hidden items-center gap-1.5 sm:flex">
          Hypopg:{" "}
          <span className={hypopg ? "text-ok" : "text-warn"}>
            {hypopg ? "Enabled" : "Not configured"}
          </span>
        </span>
      </div>

      <div className="hidden items-center gap-3 font-mono sm:flex">
        <span>
          Latency:{" "}
          <span className="text-content-secondary">
            {latency === undefined ? "—" : formatMs(latency)}
          </span>
        </span>
        <span className="h-3 w-px bg-surface-3" aria-hidden />
        <span>
          Nodes: <span className="text-content-secondary">{nodes}</span>
        </span>
        <span className="h-3 w-px bg-surface-3" aria-hidden />
        <span>
          Edges: <span className="text-content-secondary">{edges}</span>
        </span>
      </div>

      <div className="flex items-center gap-2 font-mono">
        <span>v0.4.0</span>
        <span className="h-3 w-px bg-surface-3" aria-hidden />
        <span>Build: {buildHash}</span>
      </div>
    </footer>
  );
}
