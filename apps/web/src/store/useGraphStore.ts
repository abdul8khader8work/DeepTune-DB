"use client";

import { create } from "zustand";
import type { PlanView } from "@/types/graph";

type GraphState = {
  view: PlanView;
  heatmap: boolean;
  sliderT: number;
  locked: boolean;
  selectedNodeId: string | null;
  setView: (view: PlanView) => void;
  toggleHeatmap: () => void;
  setSliderT: (value: number) => void;
  toggleLocked: () => void;
  setSelectedNode: (id: string | null) => void;
};

export const useGraphStore = create<GraphState>((set) => ({
  view: "current",
  heatmap: true,
  sliderT: 0,
  locked: false,
  selectedNodeId: null,
  setView: (view) => set({ view }),
  toggleHeatmap: () => set((state) => ({ heatmap: !state.heatmap })),
  setSliderT: (value) =>
    set({ sliderT: Math.min(1, Math.max(0, value)) }),
  toggleLocked: () => set((state) => ({ locked: !state.locked })),
  setSelectedNode: (id) => set({ selectedNodeId: id }),
}));
