export function GraphLegend() {
  return (
    <div className="absolute bottom-3 left-3 z-10 flex items-center gap-3 rounded-md border border-strong/60 bg-surface-2/90 px-2.5 py-1.5 text-[10px] text-content-tertiary backdrop-blur">
      <span className="flex items-center gap-1.5">
        <span className="h-1.5 w-1.5 rounded-full bg-danger" aria-hidden />
        Seq scan
      </span>
      <span className="flex items-center gap-1.5">
        <span className="h-1.5 w-1.5 rounded-full bg-warn" aria-hidden />
        Mixed
      </span>
      <span className="flex items-center gap-1.5">
        <span className="h-1.5 w-1.5 rounded-full bg-ok" aria-hidden />
        Indexed
      </span>
      <span className="flex items-center gap-1.5">
        <span className="h-1.5 w-1.5 rounded-full bg-ai" aria-hidden />
        GNN attention
      </span>
    </div>
  );
}
