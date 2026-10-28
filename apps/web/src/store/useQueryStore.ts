"use client";

import { create } from "zustand";
import { initialQuery } from "@/lib/mock-plan";
import type { OptimizationGoal } from "@/types/api";

type QueryState = {
  query: string;
  optimizationGoal: OptimizationGoal;
  setQuery: (query: string) => void;
  clearQuery: () => void;
  appendToken: (token: string) => void;
  setOptimizationGoal: (goal: OptimizationGoal) => void;
};

export const useQueryStore = create<QueryState>((set) => ({
  query: initialQuery,
  optimizationGoal: "balanced",
  setQuery: (query) => set({ query }),
  clearQuery: () => set({ query: "" }),
  appendToken: (token) =>
    set((state) => ({
      query: state.query.length > 0 ? `${state.query} ${token}` : token,
    })),
  setOptimizationGoal: (optimizationGoal) => set({ optimizationGoal }),
}));
