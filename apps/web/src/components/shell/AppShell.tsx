"use client";

import { useEffect, useState } from "react";
import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels";
import { TopBar } from "@/components/shell/TopBar";
import { StatusBar } from "@/components/shell/StatusBar";
import { CommandPalette } from "@/components/shell/CommandPalette";
import { LeftPane } from "@/components/left/LeftPane";
import { CenterPane } from "@/components/center/CenterPane";
import { RightPane } from "@/components/right/RightPane";
import { useSessionStore } from "@/store/useSessionStore";

export function AppShell() {
  const [paletteOpen, setPaletteOpen] = useState(false);

  useEffect(() => {
    // Probe the API once on mount so the status bar and schema panel can show
    // real capability instead of the Phase 1 mock. Failures are non-fatal.
    void useSessionStore.getState().refresh();
  }, []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const isPaletteShortcut =
        (event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k";
      if (isPaletteShortcut) {
        event.preventDefault();
        setPaletteOpen((open) => !open);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  return (
    <div className="flex h-screen w-screen flex-col overflow-hidden bg-surface-0">
      <TopBar onOpenPalette={() => setPaletteOpen(true)} />

      <main className="min-h-0 flex-1" aria-label="Optimizer workspace">
        <PanelGroup direction="horizontal" className="h-full w-full">
          <Panel defaultSize={25} minSize={18} className="min-h-0">
            <LeftPane />
          </Panel>

          <PanelResizeHandle
            aria-label="Resize input pane"
            className="w-px bg-surface-3/70 transition-colors hover:bg-ai/60 data-[resize-handle-state=drag]:bg-ai/80"
          />

          <Panel defaultSize={50} minSize={30} className="min-h-0">
            <CenterPane />
          </Panel>

          <PanelResizeHandle
            aria-label="Resize insights pane"
            className="w-px bg-surface-3/70 transition-colors hover:bg-ai/60 data-[resize-handle-state=drag]:bg-ai/80"
          />

          <Panel defaultSize={25} minSize={18} className="min-h-0">
            <RightPane />
          </Panel>
        </PanelGroup>
      </main>

      <StatusBar />
      <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} />
    </div>
  );
}
