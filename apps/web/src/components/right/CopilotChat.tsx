"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowUp, Eraser } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Textarea } from "@/components/ui/textarea";
import { ToolCallChip } from "@/components/right/ToolCallChip";
import { cn } from "@/lib/utils";
import { useCopilotStore } from "@/store/useCopilotStore";

export function CopilotChat() {
  const messages = useCopilotStore((state) => state.messages);
  const send = useCopilotStore((state) => state.send);
  const clear = useCopilotStore((state) => state.clear);
  const [value, setValue] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const lastCount = useRef(0);

  useEffect(() => {
    if (messages.length > lastCount.current) {
      bottomRef.current?.scrollIntoView({ block: "end" });
    }
    lastCount.current = messages.length;
  }, [messages]);

  const submit = () => {
    const text = value.trim();
    if (!text) return;
    send(text);
    setValue("");
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex h-9 shrink-0 items-center justify-between border-b border-subtle px-4">
        <div className="flex items-center gap-1.5">
          <h2 className="text-[13px] font-semibold text-content-primary">
            AI Copilot
          </h2>
          <span className="rounded-full border border-ai/25 bg-ai/10 px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-[0.06em] text-ai">
            beta
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
            <p className="py-6 text-center text-[11px] text-content-tertiary">
              No conversation yet. Ask why an index was chosen.
            </p>
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
                <p>{message.text}</p>
                {message.tool ? <ToolCallChip tool={message.tool} /> : null}
              </div>
            ))
          )}
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
            disabled={value.trim().length === 0}
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
