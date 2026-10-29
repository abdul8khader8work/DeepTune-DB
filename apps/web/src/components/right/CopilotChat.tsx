"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowUp, Eraser, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Textarea } from "@/components/ui/textarea";
import { ToolCallChip } from "@/components/right/ToolCallChip";
import { cn } from "@/lib/utils";
import { useAnalysisStore } from "@/store/useAnalysisStore";
import { useCopilotStore } from "@/store/useCopilotStore";

export function CopilotChat() {
  const messages = useCopilotStore((state) => state.messages);
  const streaming = useCopilotStore((state) => state.streaming);
  const thinking = useCopilotStore((state) => state.thinking);
  const send = useCopilotStore((state) => state.send);
  const clear = useCopilotStore((state) => state.clear);
  const result = useAnalysisStore((state) => state.result);
  const [value, setValue] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const last = messages[messages.length - 1];
  const lastLength = last ? last.text.length + (last.tools?.length ?? 0) : 0;

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [messages.length, lastLength, thinking]);

  const submit = () => {
    const text = value.trim();
    if (!text) return;
    send(text);
    setValue("");
  };

  const caret = streaming && last !== undefined && last.text.length > 0;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex h-9 shrink-0 items-center justify-between border-b border-subtle px-4">
        <div className="flex items-center gap-1.5">
          <h2 className="text-[13px] font-semibold text-content-primary">
            AI Copilot
          </h2>
          <span className="rounded-full border border-ai/25 bg-ai/10 px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-[0.06em] text-ai">
            {result ? "grounded" : "beta"}
          </span>
        </div>
        <Button
          variant="ghost"
          aria-label="Clear conversation"
          title="Clear conversation"
          onClick={clear}
        >
          <Eraser className="h-3.5 w-3.5" />
        </Button>
      </div>

      <ScrollArea className="min-h-0 flex-1">
        <div className="space-y-2 px-4 py-3">
          {messages.length === 0 ? (
            <div className="rounded-md border border-dashed border-strong/60 px-3 py-5 text-center">
              <Sparkles className="mx-auto h-4 w-4 text-ai" aria-hidden />
              <p className="mt-2 text-[11px] text-content-secondary">
                {result
                  ? "Ask why this plan was chosen."
                  : "Run a query to ground the copilot in a real plan."}
              </p>
              <p className="mt-1 text-[10px] text-content-tertiary">
                {result
                  ? "Answers are generated from the engine report, not a language model."
                  : "The copilot only speaks about plans it has measured."}
              </p>
            </div>
          ) : (
            messages.map((message) => (
              <div
                key={message.id}
                className={cn(
                  "rounded-md p-2 text-[11px] leading-relaxed",
                  message.role === "assistant"
                    ? "border border-subtle bg-surface-2 text-content-secondary"
                    : "ml-6 bg-content-primary text-content-inverse",
                )}
              >
                {message.tools?.map((tool, index) => (
                  <ToolCallChip key={`${message.id}-${tool.tool}-${index}`} tool={tool} />
                ))}
                {message.text || (caret && message.id === last?.id) ? (
                  <p className={message.tools?.length ? "mt-2" : undefined}>
                    {message.text}
                    {caret && message.id === last?.id ? (
                      <span
                        className="ml-0.5 inline-block h-3 w-[3px] animate-pulse-dot bg-ai align-middle"
                        aria-hidden
                      />
                    ) : null}
                  </p>
                ) : null}
              </div>
            ))
          )}

          {thinking ? (
            <div className="flex items-center gap-1.5 rounded-md border border-subtle bg-surface-2 px-2 py-1.5 text-[10px] text-content-tertiary">
              <span className="h-1 w-1 animate-pulse-dot rounded-full bg-ai" />
              <span className="text-ai">thinking</span>
              <span className="animate-pulse-dot">…</span>
            </div>
          ) : null}
          <div ref={bottomRef} />
        </div>
      </ScrollArea>

      <div className="shrink-0 border-t border-subtle p-2">
        <div className="relative">
          <Textarea
            rows={1}
            value={value}
            onChange={(event) => setValue(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                submit();
              }
            }}
            placeholder="Ask about this plan…"
            aria-label="Message the AI copilot"
            className="min-h-[36px] pr-12"
          />
          <Button
            variant="primary"
            onClick={submit}
            disabled={value.trim().length === 0 || streaming}
            aria-label="Send message"
            className="absolute bottom-1.5 right-1.5 px-2 py-1.5"
          >
            <ArrowUp className="h-3.5 w-3.5" />
          </Button>
        </div>
        <p className="mt-1 hidden text-[10px] text-content-disabled xl:block">
          Local inference · no query text leaves this machine.
        </p>
      </div>
    </div>
  );
}
