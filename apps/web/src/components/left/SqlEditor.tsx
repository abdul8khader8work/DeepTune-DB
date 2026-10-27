"use client";

import dynamic from "next/dynamic";
import { useState } from "react";
import { Trash2, Wand2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { useQueryStore } from "@/store/useQueryStore";
import { OptimizeBar } from "@/components/left/OptimizeBar";

const MonacoEditor = dynamic(
  () => import("@monaco-editor/react").then((mod) => mod.default),
  { ssr: false, loading: () => <EditorSkeleton /> },
);

function EditorSkeleton() {
  return (
    <div className="space-y-2.5 p-4" aria-hidden>
      {["w-4/5", "w-3/5", "w-2/3", "w-1/2", "w-3/4", "w-2/5"].map(
        (width, index) => (
          <div
            key={index}
            className={`h-2.5 rounded-xs bg-gradient-to-r from-surface-2 via-surface-3 to-surface-2 bg-[length:200%_100%] animate-shimmer ${width}`}
          />
        ),
      )}
    </div>
  );
}

export function SqlEditor() {
  const query = useQueryStore((state) => state.query);
  const setQuery = useQueryStore((state) => state.setQuery);
  const clearQuery = useQueryStore((state) => state.clearQuery);
  const [ready, setReady] = useState(false);

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-surface-0">
      <div className="flex h-9 shrink-0 items-center gap-1 border-b border-subtle px-2">
        <button
          type="button"
          className="relative flex h-full items-center px-2 text-[11px] font-medium text-content-primary after:absolute after:inset-x-0 after:bottom-0 after:h-px after:bg-content-primary"
          aria-current="page"
        >
          Query 1
        </button>
        <button
          type="button"
          className="rounded-sm px-2 py-1 text-[11px] text-content-tertiary transition-colors hover:bg-surface-2 hover:text-content-secondary"
          onClick={() => toast.info("Query tabs arrive with the backend in Phase 2")}
        >
          + New
        </button>
        <div className="ml-auto flex items-center gap-0.5">
          <Button
            variant="ghost"
            aria-label="Format SQL"
            title="Format SQL"
            onClick={() => toast.info("Formatter is wired to sqlglot in Phase 2")}
          >
            <Wand2 className="h-3.5 w-3.5" />
          </Button>
          <Button
            variant="ghost"
            aria-label="Clear editor"
            title="Clear editor"
            onClick={() => {
              clearQuery();
              toast.success("Editor cleared");
            }}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      <div className="relative min-h-0 flex-1">
        {ready ? null : (
          <div className="absolute inset-0 z-10 bg-surface-0">
            <EditorSkeleton />
            <p className="px-4 text-[10px] uppercase tracking-[0.08em] text-content-disabled">
              Loading editor assets…
            </p>
          </div>
        )}
        <MonacoEditor
          height="100%"
          defaultLanguage="sql"
          theme="vs-dark"
          value={query}
          onChange={(value) => setQuery(value ?? "")}
          onMount={() => setReady(true)}
          loading={<EditorSkeleton />}
          options={{
            minimap: { enabled: false },
            fontSize: 12.5,
            fontFamily: "var(--font-mono), monospace",
            fontLigatures: true,
            lineHeight: 20,
            lineNumbersMinChars: 3,
            glyphMargin: false,
            folding: false,
            renderLineHighlight: "none",
            overviewRulerLanes: 0,
            hideCursorInOverviewRuler: true,
            scrollBeyondLastLine: false,
            smoothScrolling: true,
            padding: { top: 10, bottom: 10 },
            automaticLayout: true,
            wordWrap: "on",
            tabSize: 2,
            contextmenu: false,
            scrollbar: { verticalScrollbarSize: 6, horizontalScrollbarSize: 6 },
          }}
        />
      </div>

      <OptimizeBar />
    </div>
  );
}
