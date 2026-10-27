"use client";

import { useEffect, useState } from "react";
import { Pause, Play } from "lucide-react";
import { planMetrics } from "@/lib/mock-plan";
import { formatMs } from "@/lib/utils";
import { useGraphStore } from "@/store/useGraphStore";

const speeds = [0.5, 1, 2] as const;

export function TimeSlider() {
  const view = useGraphStore((state) => state.view);
  const setView = useGraphStore((state) => state.setView);
  const sliderT = useGraphStore((state) => state.sliderT);
  const setSliderT = useGraphStore((state) => state.setSliderT);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState<number>(1);

  useEffect(() => {
    if (!playing) return;
    const interval = window.setInterval(() => {
      const current = useGraphStore.getState().sliderT;
      if (current >= 1) {
        setPlaying(false);
        return;
      }
      setSliderT(Math.min(1, current + 0.02 * speed));
    }, 50);
    return () => window.clearInterval(interval);
  }, [playing, speed, setSliderT]);

  // The view toggle pins time travel to 100%; the slider only drives the morph
  // while the "Current Plan" view is active.
  const progress = view === "optimized" ? 1 : sliderT;

  const currentLatency = Math.round(
    planMetrics.beforeMs +
      (planMetrics.afterMs - planMetrics.beforeMs) * progress,
  );

  return (
    <div className="shrink-0 border-t border-subtle bg-surface-1 px-4 py-3">
      <div className="flex items-center gap-4">
        <button
          type="button"
          onClick={() => {
            if (!playing) {
              setView("current");
              if (sliderT >= 1) setSliderT(0);
            }
            setPlaying((value) => !value);
          }}
          aria-label={playing ? "Pause time travel" : "Play time travel"}
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-content-primary text-content-inverse transition-colors hover:bg-zinc-200"
        >
          {playing ? (
            <Pause className="h-3 w-3" aria-hidden />
          ) : (
            <Play className="h-3 w-3 translate-x-px" aria-hidden />
          )}
        </button>

        <div className="min-w-0 flex-1">
          <div className="mb-2 flex items-center justify-between text-[10px] uppercase tracking-[0.08em] text-content-tertiary">
            <span>Time travel</span>
            <span className="font-mono tabular-nums text-content-secondary">
              {formatMs(currentLatency)} · {Math.round(progress * 100)}%
            </span>
          </div>

          <div className="relative h-4">
            <div className="absolute inset-x-0 top-1/2 h-1 -translate-y-1/2 rounded-full bg-surface-3">
              <div
                className="h-full rounded-full bg-content-primary transition-[width] duration-75"
                style={{ width: `${progress * 100}%` }}
              />
            </div>
            <div
              className="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full bg-content-primary ring-2 ring-surface-0 transition-[left] duration-75"
              style={{ left: `${progress * 100}%` }}
              aria-hidden
            />
            <input
              type="range"
              min={0}
              max={1}
              step={0.01}
              value={progress}
              onChange={(event) => {
                setPlaying(false);
                setView("current");
                setSliderT(Number(event.target.value));
              }}
              aria-label="Time travel between original and optimized plan"
              className="qo-range absolute inset-0 h-4 w-full cursor-pointer opacity-0"
            />
          </div>

          <div className="mt-1 flex justify-between text-[10px] text-content-disabled">
            <span>0% Original</span>
            <span>100% Optimized</span>
          </div>
        </div>

        <label className="flex shrink-0 items-center gap-1.5 text-[10px] uppercase tracking-[0.08em] text-content-tertiary">
          Speed
          <select
            value={speed}
            onChange={(event) => setSpeed(Number(event.target.value))}
            aria-label="Playback speed"
            className="rounded-sm border border-strong/70 bg-surface-2 px-1.5 py-1 font-mono text-[10px] text-content-secondary outline-none focus-visible:border-ai/60"
          >
            {speeds.map((value) => (
              <option key={value} value={value} className="bg-surface-2">
                {value}x
              </option>
            ))}
          </select>
        </label>
      </div>
    </div>
  );
}
