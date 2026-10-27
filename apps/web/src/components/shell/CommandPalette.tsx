"use client";

import { useEffect } from "react";
import { Command } from "cmdk";
import { AnimatePresence, motion } from "framer-motion";
import {
  Copy,
  Eraser,
  Flame,
  GitBranch,
  History,
  Play,
  RotateCcw,
  Search,
} from "lucide-react";
import { toast } from "sonner";
import { PaletteItem } from "@/components/shell/PaletteItem";
import { Kbd } from "@/components/ui/kbd";
import { recommendationSql } from "@/lib/mock-plan";
import { useGraphStore } from "@/store/useGraphStore";
import { useQueryStore } from "@/store/useQueryStore";

type CommandPaletteProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
};

export function CommandPalette({ open, onOpenChange }: CommandPaletteProps) {
  const toggleHeatmap = useGraphStore((state) => state.toggleHeatmap);
  const setView = useGraphStore((state) => state.setView);
  const setSliderT = useGraphStore((state) => state.setSliderT);
  const clearQuery = useQueryStore((state) => state.clearQuery);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onOpenChange(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onOpenChange]);

  const runOptimization = () => {
    onOpenChange(false);
    void toast.promise(
      new Promise<void>((resolve) => {
        window.setTimeout(resolve, 1200);
      }),
      {
        loading: "Parsing query plan…",
        success: "Plan parsed (mock). Live EXPLAIN arrives in Phase 2.",
        error: "Optimization failed",
      },
    );
  };

  const copySql = () => {
    void navigator.clipboard
      .writeText(recommendationSql)
      .then(() => toast.success("Recommendation SQL copied"))
      .catch(() => toast.error("Clipboard unavailable"));
    onOpenChange(false);
  };

  return (
    <AnimatePresence>
      {open ? (
        <motion.div
          className="fixed inset-0 z-50 flex items-start justify-center bg-surface-0/70 px-4 pt-[16vh] backdrop-blur-sm"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.15 }}
          onClick={() => onOpenChange(false)}
          role="presentation"
        >
          <motion.div
            initial={{ opacity: 0, y: -8, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -8, scale: 0.98 }}
            transition={{ duration: 0.16, ease: "easeOut" }}
            onClick={(event) => event.stopPropagation()}
            className="w-[520px] max-w-full overflow-hidden rounded-lg border border-strong bg-surface-3 shadow-modal"
            role="dialog"
            aria-modal="true"
            aria-label="Command palette"
          >
            <Command label="Command palette" loop>
              <div className="flex items-center gap-2 border-b border-subtle px-3">
                <Search
                  className="h-3.5 w-3.5 text-content-tertiary"
                  aria-hidden
                />
                <Command.Input
                  autoFocus
                  placeholder="Type a command or search…"
                  className="h-11 w-full bg-transparent text-[13px] text-content-primary outline-none placeholder:text-content-tertiary"
                />
                <Kbd>Esc</Kbd>
              </div>

              <Command.List className="max-h-[320px] overflow-y-auto p-1.5">
                <Command.Empty className="py-8 text-center text-xs text-content-tertiary">
                  No matching command.
                </Command.Empty>

                <Command.Group
                  heading="Actions"
                  className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-[10px] [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-[0.08em] [&_[cmdk-group-heading]]:text-content-tertiary"
                >
                  <PaletteItem
                    icon={Play}
                    label="Run & Optimize"
                    hint="⌘↵"
                    onSelect={runOptimization}
                  />
                  <PaletteItem
                    icon={Flame}
                    label="Toggle GNN heatmap"
                    onSelect={() => {
                      toggleHeatmap();
                      onOpenChange(false);
                    }}
                  />
                  <PaletteItem
                    icon={GitBranch}
                    label="Switch to Optimized plan"
                    onSelect={() => {
                      setView("optimized");
                      onOpenChange(false);
                    }}
                  />
                  <PaletteItem
                    icon={History}
                    label="Switch to Current plan"
                    onSelect={() => {
                      setView("current");
                      onOpenChange(false);
                    }}
                  />
                  <PaletteItem
                    icon={RotateCcw}
                    label="Reset time travel"
                    onSelect={() => {
                      setSliderT(0);
                      onOpenChange(false);
                    }}
                  />
                  <PaletteItem
                    icon={Copy}
                    label="Copy recommendation SQL"
                    onSelect={copySql}
                  />
                  <PaletteItem
                    icon={Eraser}
                    label="Clear editor"
                    onSelect={() => {
                      clearQuery();
                      onOpenChange(false);
                      toast.success("Editor cleared");
                    }}
                  />
                </Command.Group>
              </Command.List>

              <div className="flex items-center justify-between border-t border-subtle px-3 py-2 text-[10px] text-content-disabled">
                <span>↑↓ navigate · ↵ select</span>
                <span className="font-mono">DeepTune v0.1.0-beta</span>
              </div>
            </Command>
          </motion.div>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}
