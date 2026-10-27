import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["class"],
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        surface: {
          0: "#09090b",
          1: "#0f172a",
          2: "#18181b",
          3: "#27272a",
          hover: "#1f1f23",
          active: "#2a2a2f",
          selected: "rgba(99, 102, 241, 0.12)",
        },
        content: {
          primary: "#fafafa",
          secondary: "#a1a1aa",
          tertiary: "#71717a",
          disabled: "#52525b",
          inverse: "#09090b",
        },
        ai: {
          DEFAULT: "#8b5cf6",
          glow: "rgba(139, 92, 246, 0.35)",
        },
        ok: {
          DEFAULT: "#10b981",
          glow: "rgba(16, 185, 129, 0.30)",
        },
        warn: {
          DEFAULT: "#eab308",
          glow: "rgba(234, 179, 8, 0.25)",
        },
        danger: {
          DEFAULT: "#f97316",
          glow: "rgba(249, 115, 22, 0.30)",
        },
        info: {
          DEFAULT: "#06b6d4",
          glow: "rgba(6, 182, 212, 0.25)",
        },
      },
      borderColor: {
        subtle: "#1c1c1f",
        DEFAULT: "#27272a",
        strong: "#3f3f46",
        accent: "#6366f1",
      },
      fontFamily: {
        sans: ["var(--font-sans)", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
      },
      borderRadius: {
        xs: "4px",
        sm: "6px",
        md: "8px",
        lg: "12px",
      },
      boxShadow: {
        "glow-ai": "0 0 0 1px #8b5cf6, 0 0 16px rgba(139, 92, 246, 0.40)",
        "glow-ok": "0 0 0 1px #10b981, 0 0 14px rgba(16, 185, 129, 0.35)",
        "glow-danger": "0 0 0 1px #f97316, 0 0 14px rgba(249, 115, 22, 0.35)",
        floating: "0 8px 24px rgba(0, 0, 0, 0.5)",
        modal: "0 24px 64px rgba(0, 0, 0, 0.7)",
      },
      keyframes: {
        "pulse-dot": {
          "0%, 100%": { opacity: "1", transform: "scale(1)" },
          "50%": { opacity: "0.45", transform: "scale(0.85)" },
        },
        dash: {
          to: { strokeDashoffset: "-18" },
        },
        shimmer: {
          "0%": { backgroundPosition: "-200% 0" },
          "100%": { backgroundPosition: "200% 0" },
        },
        "fade-up": {
          from: { opacity: "0", transform: "translateY(6px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        "pulse-dot": "pulse-dot 2.4s ease-in-out infinite",
        dash: "dash 1.1s linear infinite",
        shimmer: "shimmer 1.6s linear infinite",
        "fade-up": "fade-up 220ms ease-out both",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};

export default config;
