"use client";

import { create } from "zustand";
import { copilotSocketUrl } from "@/lib/api";
import type { CopilotFrame } from "@/types/api";
import type { ChatMessage, ToolCall } from "@/types/graph";

type CopilotState = {
  messages: ChatMessage[];
  streaming: boolean;
  runId: string | null;
  attach: (runId: string | null) => void;
  send: (text: string) => void;
  clear: () => void;
};

let socket: WebSocket | null = null;
let streamedMessageId: string | null = null;

function nextId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `msg-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function appendChunk(chunk: string): void {
  if (!streamedMessageId) return;
  const target = streamedMessageId;
  useCopilotStore.setState((state) => ({
    messages: state.messages.map((message) =>
      message.id === target ? { ...message, text: message.text + chunk } : message,
    ),
  }));
}

function attachTool(tool: ToolCall): void {
  if (!streamedMessageId) return;
  const target = streamedMessageId;
  useCopilotStore.setState((state) => ({
    messages: state.messages.map((message) =>
      message.id === target ? { ...message, tool } : message,
    ),
  }));
}

function handleFrame(frame: CopilotFrame): void {
  if (frame.type === "ready") {
    const id = nextId();
    streamedMessageId = id;
    useCopilotStore.setState((state) => ({
      streaming: true,
      messages: [...state.messages, { id, role: "assistant", text: "" }],
    }));
    return;
  }
  if (frame.type === "token") {
    appendChunk(frame.text ?? "");
    return;
  }
  if (frame.type === "tool") {
    attachTool({
      tool: frame.tool ?? "tool",
      args: frame.args ?? "",
      result: frame.result ?? "",
      status: frame.status ?? "done",
    });
    return;
  }
  if (frame.type === "done") {
    streamedMessageId = null;
    useCopilotStore.setState({ streaming: false });
  }
}

function closeSocket(): void {
  if (socket) {
    socket.onmessage = null;
    socket.onclose = null;
    socket.onerror = null;
    socket.close();
  }
  socket = null;
  streamedMessageId = null;
}

export const useCopilotStore = create<CopilotState>((set, get) => ({
  messages: [],
  streaming: false,
  runId: null,

  attach: (runId) => {
    if (runId !== null && runId === get().runId && socket !== null) return;
    closeSocket();

    if (!runId) {
      set({ runId: null, streaming: false });
      return;
    }

    set({ runId, messages: [], streaming: true });
    const ws = new WebSocket(copilotSocketUrl(runId));
    socket = ws;

    ws.onmessage = (event: MessageEvent) => {
      try {
        handleFrame(JSON.parse(String(event.data)) as CopilotFrame);
      } catch {
        // Ignore malformed frames rather than tearing down the socket.
      }
    };
    ws.onerror = () => set({ streaming: false });
    ws.onclose = (event: CloseEvent) => {
      socket = null;
      const messages = get().messages;
      if (event.code === 4401) {
        set({
          streaming: false,
          messages: [
            ...messages,
            {
              id: nextId(),
              role: "assistant",
              text: "The copilot socket rejected the bearer token. Mint one with `python -m src.cli.token` and paste it with `storeToken(...)`.",
            },
          ],
        });
        return;
      }
      set({ streaming: false });
    };
  },

  send: (text) => {
    const question = text.trim();
    if (!question) return;

    const userMessage: ChatMessage = { id: nextId(), role: "user", text: question };

    if (socket === null || socket.readyState !== WebSocket.OPEN) {
      set((state) => ({
        messages: [
          ...state.messages,
          userMessage,
          {
            id: nextId(),
            role: "assistant",
            text: "The copilot is not attached to a run yet. Analyse a query first.",
          },
        ],
      }));
      return;
    }

    const answerId = nextId();
    streamedMessageId = answerId;
    set((state) => ({
      streaming: true,
      messages: [
        ...state.messages,
        userMessage,
        { id: answerId, role: "assistant", text: "" },
      ],
    }));
    socket.send(JSON.stringify({ type: "question", text: question }));
  },

  clear: () => {
    streamedMessageId = null;
    set({ messages: [] });
  },
}));
