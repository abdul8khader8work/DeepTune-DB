"use client";

import { useCallback, useEffect } from "react";
import { Eye, Loader2, Play, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { useAnalysisStore } from "@/store/useAnalysisStore";
import { useQueryStore } from "@/store/useQueryStore";
import type { OptimizationGoal } from "@/types/api";

const GOALS: { id: OptimizationGoal; label: string; hint: string }[] = [
  { id: "read_performance", label: "Read", hint: "Up to 3 index columns" },
  { id: "balanced", label: "Balanced", hint: "Up to 2 index columns" },
  { id: "minimal_storage", label: "Storage", hint: "Single-column indexes only" },
];

export function OptimizeBar() {
  const query = useQueryStore((state) => state.query);
  const goal = useQueryStore((state) => state.optimizationGoal);
  const setGoal = useQueryStore((state) => state.setOptimizationGoal);
  const phase = useAnalysisStore((state) => state.phase);
  const step = useAnalysisStore((state) => state.step);
  const analyse = useAnalysisStore((state) => state.analyse);

  const running = phase === "running";

  const runOptimization = useCallback(() => {
    if (running) return;
    if (query.trim().length === 0) {
      toast.error("Nothing to analyse — the editor is empty.");
      return;
    }
    void analyse(query, goal).then(() => {
      const state = useAnalysisStore.getState();
      if (state.phase === "done" && state.result) {
        const speedup = state.result.speedup_factor;
        toast.success(
          `${state.result.engine === "gnn" ? "GATv2" : "Heuristic"} plan ready — ${speedup.toFixed(2)}x predicted`,
        );
      } else if (state.phase === "error") {
        toast.error(state.error ?? "Analysis failed");
      }
    });
  }, [analyse, goal, query, running]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
        event.preventDefault();
        runOptimization();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [runOptimization]);

  return (
    <div className="flex h-11 shrink-0 items-center justify-between gap-2 overflow-hidden border-t border-subtle bg-surface-1 px-2">
      <div
        role="radiogroup"
        aria-label="Optimization goal"
        className="flex items-center gap-0.5 rounded-sm border border-strong/50 bg-surface-2 p-0.5"
      >
        {GOALS.map((item) => (
          <button
            key={item.id}
            type="button"
            role="radio"
            aria-checked={goal === item.id}
            title={item.hint}
            onClick={() => setGoal(item.id)}
            className={
              goal === item.id
                ? "rounded-xs bg-surface-3 px-1.5 py-0.5 text-[10px] font-medium text-content-primary"
                : "rounded-xs px-1.5 py-0.5 text-[10px] text-content-tertiary hover:text-content-secondary"
            }
          >
            {item.label}
          </button>
        ))}
      </div>

      <Button
        variant="secondary"
        aria-label="Explain only"
        title={step}
        onClick={() => toast.info("EXPLAIN-only mode is read-only by design", { description: step })}
      >
        <Eye className="h-3.5 w-3.5" aria-hidden />
        <span className="hidden xl:inline">Explain Only</span>
      </Button>

      <Button
        variant="primary"
        onClick={runOptimization}
        disabled={running}
        aria-busy={running}
      >
        {running ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
        ) : (
          <Play className="h-3.5 w-3.5" aria-hidden />
        )}
        {running ? "Optimizing…" : "Run & Optimize"}
        <Sparkles className="hidden h-3.5 w-3.5 xl:inline" aria-hidden />
      </Button>
    </div>
  );
}
