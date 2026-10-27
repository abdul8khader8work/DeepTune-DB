import * as React from "react";
import { cn } from "@/lib/utils";

export type InputProps = React.InputHTMLAttributes<HTMLInputElement>;

export const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, ...props }, ref) => (
    <input
      ref={ref}
      className={cn(
        "h-7 w-full rounded-sm border border-strong/70 bg-surface-2 px-2 text-xs text-content-primary placeholder:text-content-tertiary focus-visible:border-ai/60 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ai/40",
        className,
      )}
      {...props}
    />
  ),
);
Input.displayName = "Input";
