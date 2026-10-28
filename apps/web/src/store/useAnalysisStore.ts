"use client";

import { create } from "zustand";
import { ApiError, api } from "@/lib/api";
import { useCopilotStore } from "@/store/useCopilotStore";
import { useSessionStore } from "@/store/useSessionStore";
import type { AnalysisResult, OptimizationGoal } from "@/types/api";

export type AnalysisPhase = "idle" | "running" | "done" | "error";

const POLL_INTERVAL_MS = 400;
const MAX_POLLS = 150;

type AnalysisState = {
  phase: AnalysisPhase;
  progress: number;
  step: string;
  runId: string | null;
  result: AnalysisResult | null;
  error: string | null;
  analyse: (sql: string, goal: OptimizationGoal) => Promise<void>;
  reset: () => void;
};

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

function describe(error: unknown): string {
  if (error instanceof ApiError) {
    return error.suggestion ? `${error.message} ${error.suggestion}` : error.message;
  }
  return error instanceof Error ? error.message : "Unexpected error";
}

export const useAnalysisStore = create<AnalysisState>((set, get) => ({
  phase: "idle",
  progress: 0,
  step: "Idle",
  runId: null,
  result: null,
  error: null,

  reset: () => {
    useCopilotStore.getState().attach(null);
    set({ phase: "idle", progress: 0, step: "Idle", runId: null, result: null, error: null });
  },

  analyse: async (sql, goal) => {
    if (get().phase === "running") return;
    set({ phase: "running", progress: 0, step: "Connecting…", error: null, result: null });

    try {
      const connectionId = await useSessionStore.getState().ensureConnection();
      const accepted = await api.analyze({
        connection_id: connectionId,
        sql_query: sql,
        optimization_goal: goal,
      });
      set({ runId: accepted.run_id, step: accepted.message });

      for (let attempt = 0; attempt < MAX_POLLS; attempt += 1) {
        const status = await api.runStatus(accepted.run_id);
        set({ progress: status.progress_percentage, step: status.current_step_log });

        if (status.status === "failed") {
          throw new Error(status.current_step_log);
        }
        if (status.status === "completed") {
          const result = await api.runResults(accepted.run_id);
          set({ phase: "done", progress: 100, result, step: "Analysis complete." });
          useCopilotStore.getState().attach(accepted.run_id);
          return;
        }
        await sleep(POLL_INTERVAL_MS);
      }
      throw new Error("Analysis timed out before the plan was ready.");
    } catch (error) {
      set({ phase: "error", error: describe(error), step: "Analysis failed." });
    }
  },
}));
