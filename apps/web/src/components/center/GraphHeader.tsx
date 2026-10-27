"use client";

import { Flame } from "lucide-react";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";
import { useGraphStore } from "@/store/useGraphStore";
import type { PlanView } from "@/types/graph";

const views: { id: PlanView; label: string }[] = [
  { id: "current", label: "Current Plan" },
  { id: "optimized", label: "Optimized Plan" },
];

export function GraphHeader() {
  const view = useGraphStore((state) => state.view);
  const setView = useGraphStore((state) => state.setView);
  const heatmap = useGraphStore((state) => state.heatmap);
  const toggleHeatmap = useGraphStore((state) => state.toggleHeatmap);

  return (
    <div className="absolute left-3 top-2 z-10 flex items-center gap-2 rounded-md border border-strong/60 bg-surface-2/90 p-1 backdrop-blur">
      <div role="tablist" aria-label="Plan view" className="flex items-center gap-0.5">
        {views.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={view === item.id}
            onClick={() => setView(item.id)}
            className={cn(
              "rounded-sm px-2.5 py-1 text-[11px] font-medium transition-colors",
              view === item.id
                ? "bg-surface-3 text-content-primary shadow-sm"
                : "text-content-tertiary hover:text-content-secondary",
            )}
          >
            {item.label}
          </button>
        ))}
      </div>

      <span className="h-4 w-px bg-surface-3" aria-hidden />

      <label className="flex cursor-pointer items-center gap-1.5 pr-1 text-[11px] text-content-tertiary">
        <Flame className="h-3 w-3 text-ai" aria-hidden />
        <span className="hidden xl:inline">GNN heatmap</span>
        <Switch
          checked={heatmap}
          onCheckedChange={toggleHeatmap}
          aria-label="Toggle GNN attention heatmap"
        />
      </label>
    </div>
  );
}
