/**
 * Design tokens — the single source of truth for the DeepTune UI.
 *
 * Components must consume these through Tailwind utility classes
 * (e.g. `bg-surface-2`, `text-content-secondary`, `border-strong`).
 * Never hardcode a hex value inside JSX.
 */

export const tokens = {
  surface: {
    0: "#09090b",
    1: "#0f172a",
    2: "#18181b",
    3: "#27272a",
    hover: "#1f1f23",
    active: "#2a2a2f",
    selected: "rgba(99, 102, 241, 0.12)",
  },
  border: {
    subtle: "#1c1c1f",
    default: "#27272a",
    strong: "#3f3f46",
    accent: "#6366f1",
  },
  text: {
    primary: "#fafafa",
    secondary: "#a1a1aa",
    tertiary: "#71717a",
    disabled: "#52525b",
    inverse: "#09090b",
  },
  accent: {
    ai: "#8b5cf6",
    success: "#10b981",
    warning: "#eab308",
    danger: "#f97316",
    info: "#06b6d4",
    muted: "#3f3f46",
  },
  radius: {
    xs: "4px",
    sm: "6px",
    md: "8px",
    lg: "12px",
    full: "9999px",
  },
  layout: {
    topbar: "48px",
    statusbar: "32px",
    leftPane: "25%",
    centerPane: "50%",
    rightPane: "25%",
  },
} as const;

export type Tokens = typeof tokens;

/**
 * The four permitted button variants. Defined once here and consumed by
 * `components/ui/button.tsx` so the dictionary cannot drift.
 */
export const buttonStyles = {
  primary:
    "bg-white text-black font-medium rounded-md px-3 py-1.5 text-sm hover:bg-zinc-200 transition-colors",
  secondary:
    "bg-zinc-900 border border-zinc-800 text-zinc-300 font-medium rounded-md px-3 py-1.5 text-sm hover:bg-zinc-800 hover:text-white transition-colors",
  ghost:
    "bg-transparent text-zinc-400 rounded-md p-1.5 hover:bg-zinc-800 hover:text-white transition-colors",
  destructive:
    "bg-transparent text-red-400 rounded-md px-3 py-1.5 text-sm hover:bg-red-500/10 transition-colors",
} as const;

export type ButtonVariant = keyof typeof buttonStyles;
