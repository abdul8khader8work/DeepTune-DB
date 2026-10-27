import * as React from "react";
import { cn } from "@/lib/utils";

export type TextareaProps = React.TextareaHTMLAttributes<HTMLTextAreaElement>;

export const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className, ...props }, ref) => (
    <textarea
      ref={ref}
      className={cn(
        "w-full resize-none rounded-md border border-strong/70 bg-surface-2 px-3 py-2 text-[13px] text-content-primary placeholder:text-content-tertiary focus-visible:border-ai/60 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ai/40",
        className,
      )}
      {...props}
    />
  ),
);
Textarea.displayName = "Textarea";
