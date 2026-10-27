"use client";

import { useReactFlow } from "@xyflow/react";
import { Lock, Maximize2, Minus, Plus, Unlock } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useGraphStore } from "@/store/useGraphStore";

export function GraphToolbar() {
  const { zoomIn, zoomOut, fitView } = useReactFlow();
  const locked = useGraphStore((state) => state.locked);
  const toggleLocked = useGraphStore((state) => state.toggleLocked);

  return (
    <div className="absolute right-3 top-2 z-10 flex items-center gap-0.5 rounded-md border border-strong/60 bg-surface-2/90 p-0.5 backdrop-blur">
      <Button
        variant="ghost"
        aria-label="Zoom in"
        title="Zoom in"
        onClick={() => zoomIn({ duration: 200 })}
      >
        <Plus className="h-3.5 w-3.5" />
      </Button>
      <Button
        variant="ghost"
        aria-label="Zoom out"
        title="Zoom out"
        onClick={() => zoomOut({ duration: 200 })}
      >
        <Minus className="h-3.5 w-3.5" />
      </Button>
      <Button
        variant="ghost"
        aria-label="Fit to screen"
        title="Fit to screen"
        onClick={() => fitView({ padding: 0.16, duration: 320 })}
      >
        <Maximize2 className="h-3.5 w-3.5" />
      </Button>
      <span className="mx-0.5 h-4 w-px bg-surface-3" aria-hidden />
      <Button
        variant="ghost"
        aria-label={locked ? "Unlock layout" : "Lock layout"}
        title={locked ? "Unlock layout" : "Lock layout"}
        aria-pressed={locked}
        onClick={toggleLocked}
        className={locked ? "text-ai hover:text-ai" : undefined}
      >
        {locked ? (
          <Lock className="h-3.5 w-3.5" />
        ) : (
          <Unlock className="h-3.5 w-3.5" />
        )}
      </Button>
    </div>
  );
}
