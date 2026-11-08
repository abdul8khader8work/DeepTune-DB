"use client";

import { create } from "zustand";
import { ApiError, api, optimizeSocketUrl } from "@/lib/api";
import { useCopilotStore } from "@/store/useCopilotStore";
import { useSessionStore } from "@/store/useSessionStore";
import type { AnalysisResult, OptimizationGoal, OptimizeFrame } from "@/types/api";

export type AnalysisPhase = "idle" | "running" | "done" | "error";

const STREAM_TIMEOUT_MS = 90_000;

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

type StreamHandlers = {
  /** `null` keeps the current percentage (a log line has no progress value). */
  onProgress: (percentage: number | null, step: string) => void;
};

function describe(error: unknown): string {
  if (error instanceof ApiError) {
    return error.suggestion ? `${error.message} ${error.suggestion}` : error.message;
  }
  return error instanceof Error ? error.message : "Unexpected error";
}

/**
 * Stream one run from `WS /ws/optimize/{run_id}` (Patch 3).
 *
 * No `setInterval` and no REST polling: the socket emits `progress`,
 * `log_update`, `complete`, `error`, and a `ping` heartbeat. `seq` is monotonic,
 * so a snapshot that raced a live broadcast is discarded instead of rewinding
 * the progress bar.
 */
function awaitRun(runId: string, handlers: StreamHandlers): Promise<AnalysisResult> {
  return new Promise((resolve, reject) => {
    const socket = new WebSocket(optimizeSocketUrl(runId));
    let lastSeq = -1;
    let settled = false;
    let watchdog = 0;

    const finish = (error: Error | null, result?: AnalysisResult): void => {
      if (settled) return;
      settled = true;
      window.clearTimeout(watchdog);
      socket.onmessage = null;
      socket.onerror = null;
      socket.onclose = null;
      socket.close();
      if (error) {
        reject(error);
        return;
      }
      if (result) {
        resolve(result);
        return;
      }
      reject(new Error("The progress stream ended without a result."));
    };

    watchdog = window.setTimeout(() => {
      finish(new Error("Analysis timed out before the plan was ready."));
    }, STREAM_TIMEOUT_MS);

    socket.onmessage = (event: MessageEvent) => {
      let frame: OptimizeFrame;
      try {
        frame = JSON.parse(String(event.data)) as OptimizeFrame;
      } catch {
        return; // Ignore malformed frames rather than tearing down the socket.
      }
      if (frame.type === "ping") return;
      if (frame.seq < lastSeq) return;
      lastSeq = frame.seq;

      if (frame.type === "progress") {
        handlers.onProgress(
          frame.payload.percentage,
          frame.payload.message || frame.payload.step,
        );
        return;
      }
      if (frame.type === "log_update") {
        handlers.onProgress(null, frame.payload.text);
        return;
      }
      if (frame.type === "complete") {
        finish(null, frame.payload);
        return;
      }
      finish(new Error(frame.payload.message));
    };

    socket.onerror = () => {
      finish(new Error("The progress WebSocket failed to connect."));
    };
    socket.onclose = (event: CloseEvent) => {
      if (settled) return;
      finish(
        new Error(
          event.code === 4401
            ? "The progress socket rejected the bearer token. Mint one with `python -m src.cli.token` and paste it with `storeToken(...)`."
            : "The progress stream closed before the analysis finished.",
        ),
      );
    };
  });
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

    const report = (percentage: number | null, step: string): void => {
      set((state) => ({
        progress:
          percentage === null
            ? state.progress
            : Math.max(state.progress, Math.min(100, percentage)),
        step: step || state.step,
      }));
    };

    try {
      const connectionId = await useSessionStore.getState().ensureConnection();
      const accepted = await api.analyze({
        connection_id: connectionId,
        sql_query: sql,
        optimization_goal: goal,
      });
      set({ runId: accepted.run_id, step: accepted.message });

      const result = await awaitRun(accepted.run_id, { onProgress: report });
      set({ phase: "done", progress: 100, result, step: "Analysis complete." });
      useCopilotStore.getState().attach(accepted.run_id);
    } catch (error) {
      set({ phase: "error", error: describe(error), step: "Analysis failed." });
    }
  },
}));
