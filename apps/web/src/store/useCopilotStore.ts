"use client";

import { create } from "zustand";
import type { ChatMessage } from "@/types/graph";

const seedMessages: ChatMessage[] = [
  {
    id: "seed-1",
    role: "assistant",
    text: "The planner is doing a sequential scan on orders because the composite predicate has no matching prefix index. I checked column selectivity before recommending anything.",
    tool: {
      tool: "analyze_column_selectivity",
      args: "orders.status, orders.order_date",
      result: "0.001",
      status: "done",
    },
  },
  {
    id: "seed-2",
    role: "user",
    text: "Why customer_id first in the index?",
  },
  {
    id: "seed-3",
    role: "assistant",
    text: "It is the join key, so it enables an index-nested-loop path. order_date is second to preserve the left-prefix rule for your range filter. INCLUDE keeps the heap fetch off the hot path.",
  },
];

type CopilotState = {
  messages: ChatMessage[];
  send: (text: string) => void;
  clear: () => void;
};

function nextId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `msg-${Date.now()}`;
}

export const useCopilotStore = create<CopilotState>((set) => ({
  messages: seedMessages,
  send: (text) =>
    set((state) => ({
      messages: [
        ...state.messages,
        { id: nextId(), role: "user", text },
        {
          id: nextId(),
          role: "assistant",
          text: "Copilot reasoning is wired to the ML engine in Phase 4. For now this is a UI shell: your question is captured, but no model is called.",
        },
      ],
    })),
  clear: () => set({ messages: [] }),
}));
