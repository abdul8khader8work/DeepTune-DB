import { planEdges, planMetrics } from "@/lib/mock-plan";

const buildHash = "8a9f2c";

export function StatusBar() {
  return (
    <footer className="flex h-8 shrink-0 items-center justify-between border-t border-subtle bg-surface-0 px-4 text-[11px] text-content-tertiary">
      <div className="flex items-center gap-3">
        <span className="flex items-center gap-1.5">
          <span className="h-1 w-1 rounded-full bg-ai" aria-hidden />
          GNN Model:{" "}
          <span className="font-mono text-content-secondary">v1.2</span>
          <span className="text-ok">(Active)</span>
        </span>
        <span className="hidden h-3 w-px bg-surface-3 sm:block" aria-hidden />
        <span className="hidden items-center gap-1.5 sm:flex">
          Hypopg: <span className="text-ok">Enabled</span>
        </span>
      </div>

      <div className="hidden items-center gap-3 font-mono sm:flex">
        <span>
          Latency: <span className="text-content-secondary">42ms</span>
        </span>
        <span className="h-3 w-px bg-surface-3" aria-hidden />
        <span>
          Nodes:{" "}
          <span className="text-content-secondary">{planMetrics.nodeCount}</span>
        </span>
        <span className="h-3 w-px bg-surface-3" aria-hidden />
        <span>
          Edges:{" "}
          <span className="text-content-secondary">{planEdges.length}</span>
        </span>
      </div>

      <div className="flex items-center gap-2 font-mono">
        <span>v0.1.0-beta</span>
        <span className="h-3 w-px bg-surface-3" aria-hidden />
        <span>Build: {buildHash}</span>
      </div>
    </footer>
  );
}
