"use client";

import { ChevronRight, Database, Settings, UserRound } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Kbd } from "@/components/ui/kbd";

type TopBarProps = {
  onOpenPalette: () => void;
};

const breadcrumbs = ["public", "orders", "Query #42"];

export function TopBar({ onOpenPalette }: TopBarProps) {
  return (
    <header className="flex h-12 shrink-0 items-center gap-3 border-b border-subtle bg-surface-0 px-4">
      <div className="flex items-center gap-2">
        <div className="flex h-6 w-6 items-center justify-center rounded-sm border border-ai/30 bg-ai/10">
          <Database className="h-3.5 w-3.5 text-ai" aria-hidden />
        </div>
        <span className="text-[13px] font-semibold tracking-tight text-content-primary">
          DeepTune
        </span>
        <span className="hidden text-[11px] text-content-tertiary lg:inline">
          query optimizer
        </span>
      </div>

      <div className="ml-2 flex items-center gap-1.5 rounded-full border border-ok/20 bg-ok/10 px-2 py-0.5 text-[11px] text-ok">
        <span className="h-1.5 w-1.5 animate-pulse-dot rounded-full bg-ok" />
        <span className="font-medium">Connected: prod_db</span>
      </div>

      <nav
        aria-label="Breadcrumb"
        className="hidden flex-1 items-center justify-center gap-1 text-[12px] text-content-tertiary md:flex"
      >
        {breadcrumbs.map((crumb, index) => (
          <span key={crumb} className="flex items-center gap-1">
            {index > 0 ? (
              <ChevronRight className="h-3 w-3 text-content-disabled" aria-hidden />
            ) : null}
            <span
              className={
                index === breadcrumbs.length - 1
                  ? "font-medium text-content-secondary"
                  : undefined
              }
            >
              {crumb}
            </span>
          </span>
        ))}
      </nav>

      <div className="ml-auto flex items-center gap-1.5">
        <Button
          variant="secondary"
          onClick={onOpenPalette}
          className="h-7 gap-1.5 px-2 py-0 text-[11px] text-content-tertiary"
          aria-label="Open command palette"
        >
          Search
          <Kbd className="h-4 border-strong/70 bg-surface-3 px-1 text-[9px]">
            ⌘K
          </Kbd>
        </Button>
        <Button variant="ghost" aria-label="Settings" title="Settings">
          <Settings className="h-3.5 w-3.5" />
        </Button>
        <div
          className="ml-0.5 flex h-6 w-6 items-center justify-center rounded-full border border-strong bg-surface-2 text-content-secondary"
          aria-label="Signed in as abdul"
          title="abdul"
        >
          <UserRound className="h-3 w-3" aria-hidden />
        </div>
      </div>
    </header>
  );
}
