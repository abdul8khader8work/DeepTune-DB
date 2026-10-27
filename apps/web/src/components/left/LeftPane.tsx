import { SqlEditor } from "@/components/left/SqlEditor";
import { SchemaExplorer } from "@/components/left/SchemaExplorer";

export function LeftPane() {
  return (
    <section
      aria-label="Query input and schema"
      className="flex h-full min-h-0 flex-col overflow-hidden bg-surface-1"
    >
      <div className="flex min-h-0 flex-[3] flex-col">
        <SqlEditor />
      </div>
      <div className="flex min-h-0 flex-[2] flex-col border-t border-subtle">
        <SchemaExplorer />
      </div>
    </section>
  );
}
