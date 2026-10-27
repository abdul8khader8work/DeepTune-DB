"use client";

import { ReactFlowProvider } from "@xyflow/react";
import { QOGraph } from "@/components/center/QOGraph";
import { GraphHeader } from "@/components/center/GraphHeader";
import { GraphToolbar } from "@/components/center/GraphToolbar";
import { GraphLegend } from "@/components/center/GraphLegend";
import { TimeSlider } from "@/components/center/TimeSlider";

export function CenterPane() {
  return (
    <section
      aria-label="Query execution plan"
      className="flex h-full min-h-0 flex-col overflow-hidden bg-surface-0"
    >
      <div className="relative min-h-0 flex-1">
        <ReactFlowProvider>
          <div className="absolute inset-x-0 bottom-0 top-11">
            <QOGraph />
          </div>
          <GraphHeader />
          <GraphToolbar />
          <GraphLegend />
        </ReactFlowProvider>
      </div>
      <TimeSlider />
    </section>
  );
}
