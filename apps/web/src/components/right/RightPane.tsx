import { MetricHero } from "@/components/right/MetricHero";
import { RecommendCard } from "@/components/right/RecommendCard";
import { CopilotChat } from "@/components/right/CopilotChat";

export function RightPane() {
  return (
    <aside
      aria-label="Insights and AI copilot"
      className="flex h-full min-h-0 flex-col overflow-hidden bg-surface-1"
    >
      <div className="shrink-0 border-b border-subtle p-3">
        <MetricHero />
      </div>
      <div className="flex min-h-0 flex-[3] flex-col border-b border-subtle">
        <RecommendCard />
      </div>
      <div className="flex min-h-0 flex-[2] flex-col">
        <CopilotChat />
      </div>
    </aside>
  );
}
