import { CheckCircle2, Loader2 } from "lucide-react";
import type { ToolCall } from "@/types/graph";

type ToolCallChipProps = {
  tool: ToolCall;
};

export function ToolCallChip({ tool }: ToolCallChipProps) {
  return (
    <div className="mt-2 flex items-start gap-1.5 rounded-sm border border-strong/60 bg-surface-0 px-2 py-1.5 font-mono text-[10px] leading-relaxed text-info">
      {tool.status === "running" ? (
        <Loader2 className="mt-0.5 h-2.5 w-2.5 shrink-0 animate-spin" aria-hidden />
      ) : (
        <CheckCircle2 className="mt-0.5 h-2.5 w-2.5 shrink-0 text-ok" aria-hidden />
      )}
      <span className="min-w-0">
        <span className="text-content-tertiary">[Tool: </span>
        {tool.tool}
        <span className="text-content-tertiary">]</span>
        <span className="text-content-tertiary"> → </span>
        <span className="break-all">{tool.result}</span>
      </span>
    </div>
  );
}
