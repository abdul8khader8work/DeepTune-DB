"use client";

import { create } from "zustand";
import { initialQuery } from "@/lib/mock-plan";

export type RunStatus = "idle" | "running" | "done";

type QueryState = {
  query: string;
  runStatus: RunStatus;
  setQuery: (query: string) => void;
  clearQuery: () => void;
  appendToken: (token: string) => void;
  setRunStatus: (status: RunStatus) => void;
};

export const useQueryStore = create<QueryState>((set) => ({
  query: initialQuery,
  runStatus: "idle",
  setQuery: (query) => set({ query }),
  clearQuery: () => set({ query: "" }),
  appendToken: (token) =>
    set((state) => ({
      query: state.query.length > 0 ? `${state.query} ${token}` : token,
    })),
  setRunStatus: (runStatus) => set({ runStatus }),
}));
