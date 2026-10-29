"use client";

import { useState } from "react";
import { CheckCircle2, ChevronRight, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ToolCall } from "@/types/graph";

type ToolCallChipProps = {
  tool: ToolCall;
};

/**
 * One tool frame, rendered as `[tool] → result` and expandable for the args.
 *
 * Collapsed by default: the trace is context, not the answer, so it should not
 * push the prose out of view. The whole row is the toggle so the hit target is
 * comfortable at a 10px font size.
 */
export function ToolCallChip({ tool }: ToolCallChipProps) {
  const [open, setOpen] = useState(false);
  const running = tool.status === "running";

  return (
    <div className="mt-2 overflow-hidden rounded-sm border border-strong/60 bg-surface-0">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        title={open ? "Hide tool arguments" : "Show tool arguments"}
        className="flex w-full items-start gap-1.5 px-2 py-1.5 text-left font-mono text-[10px] leading-relaxed text-info transition-colors hover:bg-surface-hover"
      >
        <ChevronRight
          className={cn(
            "mt-0.5 h-2.5 w-2.5 shrink-0 text-content-tertiary transition-transform",
            open && "rotate-90",
          )}
          aria-hidden
        />
        {running ? (
          <Loader2 className="mt-0.5 h-2.5 w-2.5 shrink-0 animate-spin" aria-hidden />
        ) : (
          <CheckCircle2 className="mt-0.5 h-2.5 w-2.5 shrink-0 text-ok" aria-hidden />
        )}
        <span className="min-w-0 truncate">
          <span className="text-content-tertiary">[</span>
          {tool.tool}
          <span className="text-content-tertiary">]</span>
          <span className="text-content-tertiary"> → </span>
          {tool.result}
        </span>
      </button>
      {open ? (
        <dl className="space-y-1 border-t border-strong/60 px-2 py-1.5 font-mono text-[10px] leading-relaxed">
          <div>
            <dt className="text-content-tertiary">args</dt>
            <dd className="break-all text-content-secondary">{tool.args || "—"}</dd>
          </div>
          <div>
            <dt className="text-content-tertiary">result</dt>
            <dd className="break-all text-content-primary">{tool.result || "—"}</dd>
          </div>
        </dl>
      ) : null}
    </div>
  );
}
