"use client";

import { useCallback, useEffect } from "react";
import { Eye, Play, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { useQueryStore } from "@/store/useQueryStore";

export function OptimizeBar() {
  const runStatus = useQueryStore((state) => state.runStatus);
  const setRunStatus = useQueryStore((state) => state.setRunStatus);

  const runOptimization = useCallback(() => {
    if (runStatus === "running") return;
    setRunStatus("running");
    void toast.promise(
      new Promise<void>((resolve) => {
        window.setTimeout(resolve, 1400);
      }),
      {
        loading: "Running EXPLAIN in a 5s sandbox…",
        success: () => {
          setRunStatus("done");
          return "Plan captured (mock). Live EXPLAIN arrives in Phase 2.";
        },
        error: () => {
          setRunStatus("idle");
          return "Run failed";
        },
      },
    );
  }, [runStatus, setRunStatus]);

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
      <Button
        variant="secondary"
        aria-label="Explain only"
        title="Explain only"
        onClick={() =>
          toast.info("EXPLAIN-only mode is read-only by design — wired in Phase 2")
        }
      >
        <Eye className="h-3.5 w-3.5" aria-hidden />
        <span className="hidden xl:inline">Explain Only</span>
      </Button>

      <Button
        variant="primary"
        onClick={runOptimization}
        disabled={runStatus === "running"}
        aria-busy={runStatus === "running"}
      >
        <Play className="h-3.5 w-3.5" aria-hidden />
        {runStatus === "running" ? "Optimizing…" : "Run & Optimize"}
        <Sparkles className="hidden h-3.5 w-3.5 xl:inline" aria-hidden />
      </Button>
    </div>
  );
}
