"use client";

import { motionValue } from "framer-motion";

/**
 * Patch 3 — the time-travel morph runs on a Framer Motion value, not on React.
 *
 * Scrubbing used to push `sliderT` into the zustand store, which re-rendered
 * `QOGraph` and rebuilt the whole node array ~20 times a second; React Flow then
 * re-measured every node and the graph ran at 23 fps. The measurement showed the
 * re-render (and Framer's projection `measureScroll`) as the cost, not the
 * animation itself.
 *
 * So the slider now writes one module-level motion value, and each node
 * subscribes to it directly: numbers are written to `textContent`, tones are
 * animated with `opacity`, and React only re-renders once — at the 50% identity
 * flip where the operator label, icon and border actually change.
 */
export const morphProgress = motionValue(0);

/** Read the morph position, clamped to `[0, 1]`. */
export function currentMorph(): number {
  return Math.min(1, Math.max(0, morphProgress.get()));
}

/** Linear interpolation between the original and the optimized value. */
export function lerp(from: number, to: number, t = currentMorph()): number {
  return from + (to - from) * t;
}
