import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium leading-none",
  {
    variants: {
      variant: {
        ok: "border-ok/20 bg-ok/10 text-ok",
        warn: "border-warn/20 bg-warn/10 text-warn",
        danger: "border-danger/20 bg-danger/10 text-danger",
        ai: "border-ai/25 bg-ai/10 text-ai",
        info: "border-info/20 bg-info/10 text-info",
        muted: "border-strong/60 bg-surface-3/60 text-content-secondary",
      },
    },
    defaultVariants: {
      variant: "muted",
    },
  },
);

export type BadgeProps = React.HTMLAttributes<HTMLSpanElement> &
  VariantProps<typeof badgeVariants>;

export function Badge({ className, variant, ...props }: BadgeProps) {
  return (
    <span className={cn(badgeVariants({ variant }), className)} {...props} />
  );
}

export { badgeVariants };
