import * as React from "react";
import { cn } from "@/lib/utils";

export function Kbd({
  className,
  children,
}: React.HTMLAttributes<HTMLElement>) {
  return (
    <kbd
      className={cn(
        "inline-flex h-5 items-center rounded-xs border border-strong/80 bg-surface-2 px-1.5 font-mono text-[10px] font-medium text-content-tertiary",
        className,
      )}
    >
      {children}
    </kbd>
  );
}
