"use client";

import { Copy, Database, FileCode2 } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  planMetrics,
  recommendationSql,
} from "@/lib/mock-plan";

export function RecommendCard() {
  const copySql = () => {
    void navigator.clipboard
      .writeText(recommendationSql)
      .then(() => toast.success("Recommendation SQL copied"))
      .catch(() => toast.error("Clipboard unavailable"));
  };

  const showMigration = () => {
    toast.info("Migration script preview opens in Phase 2", {
      description: "CREATE INDEX CONCURRENTLY is never auto-applied.",
    });
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex shrink-0 items-start justify-between gap-2 px-4 pb-2 pt-3">
        <div className="min-w-0">
          <h2 className="text-[13px] font-semibold text-content-primary">
            Recommended Action
          </h2>
          <div className="mt-1 flex flex-wrap items-center gap-1.5">
            <Badge variant="ok">Confidence {planMetrics.confidence}%</Badge>
            <span className="truncate text-[10px] text-content-tertiary">
              Composite B-tree · orders
            </span>
          </div>
        </div>
        <Button
          variant="ghost"
          aria-label="View migration script"
          title="View migration script"
          onClick={showMigration}
        >
          <FileCode2 className="h-3.5 w-3.5" />
        </Button>
      </div>

      <ScrollArea className="min-h-0 flex-1">
        <div className="px-4">
          <pre className="whitespace-pre-wrap break-words rounded-md border border-strong/70 bg-surface-0 p-2.5 font-mono text-[9px] leading-[1.5] xl:p-3 xl:text-[11px]">
          <code>
            <span className="text-ai">CREATE INDEX CONCURRENTLY</span>
            {"\n  "}
            <span className="text-content-primary">idx_orders_customer_date</span>
            {"\n  "}
            <span className="text-info">ON</span> orders (customer_id,
            {"\n             "}
            order_date <span className="text-warn">DESC</span>)
            {"\n  "}
            <span className="text-info">INCLUDE</span> (status, total)
            {"\n  "}
            <span className="text-info">WHERE</span> status ={" "}
            <span className="text-ok">&apos;paid&apos;</span>;
          </code>
        </pre>

          <p className="py-2 text-center text-[10px] text-content-disabled">
            Write amplification +2.1% · storage +0.4%
          </p>
        </div>
      </ScrollArea>

      <div className="shrink-0 space-y-1.5 px-4 pb-2.5 pt-1.5">
        <Button
          variant="primary"
          className="w-full"
          onClick={() =>
            toast.info("Shadow DB validation lands in Phase 2", {
              description: "No DDL is executed against your database.",
            })
          }
        >
          <Database className="h-3.5 w-3.5" aria-hidden />
          Apply to Shadow DB
        </Button>
        <Button variant="secondary" className="w-full" onClick={copySql}>
          <Copy className="h-3.5 w-3.5" aria-hidden />
          Copy SQL
        </Button>
      </div>
    </div>
  );
}
