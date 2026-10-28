"use client";

import { useCallback, useEffect, useState } from "react";
import { Copy, Database, FileCode2, Loader2, RotateCcw } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { ApiError, api } from "@/lib/api";
import { planMetrics, recommendationSql } from "@/lib/mock-plan";
import { formatBytes } from "@/lib/utils";
import { useAnalysisStore } from "@/store/useAnalysisStore";

type ApplyState = "idle" | "applying" | "applied" | "reverting";

function describe(error: unknown): string {
  if (error instanceof ApiError) {
    return error.suggestion ? `${error.message} ${error.suggestion}` : error.message;
  }
  return error instanceof Error ? error.message : "Unexpected error";
}

export function RecommendCard() {
  const result = useAnalysisStore((state) => state.result);
  const recommendation = result?.recommendations[0] ?? null;
  const [status, setStatus] = useState<ApplyState>("idle");

  useEffect(() => {
    setStatus("idle");
  }, [result?.run_id]);

  const sql = recommendation?.sql_statement ?? recommendationSql;
  const confidence = recommendation
    ? Math.round(recommendation.confidence_score * 100)
    : planMetrics.confidence;
  const columns = recommendation?.target_columns.join(", ") ?? "customer_id, order_date";

  const copySql = useCallback(() => {
    void navigator.clipboard
      .writeText(sql)
      .then(() => toast.success("Recommendation SQL copied"))
      .catch(() => toast.error("Clipboard unavailable"));
  }, [sql]);

  const apply = useCallback(async () => {
    if (!recommendation) {
      toast.info("This is the sample plan", {
        description: "Connect a database and run a query to apply a real index.",
      });
      return;
    }
    setStatus("applying");
    try {
      const response = await api.applyRecommendation(recommendation.id);
      setStatus("applied");
      toast.success("Hypothetical index applied", {
        description: `${response.message} (${response.validated_execution_time_ms.toFixed(1)} ms)`,
      });
    } catch (error) {
      setStatus("idle");
      toast.error("Shadow DB rejected the index", { description: describe(error) });
    }
  }, [recommendation]);

  const revert = useCallback(async () => {
    if (!recommendation) return;
    setStatus("reverting");
    try {
      await api.revertRecommendation(recommendation.id);
      setStatus("idle");
      toast.success("Hypothetical index dropped");
    } catch (error) {
      setStatus("applied");
      toast.error("Could not revert the index", { description: describe(error) });
    }
  }, [recommendation]);

  const busy = status === "applying" || status === "reverting";
  const applied = status === "applied";

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex shrink-0 items-start justify-between gap-2 px-4 pb-2 pt-3">
        <div className="min-w-0">
          <h2 className="text-[13px] font-semibold text-content-primary">
            Recommended Action
          </h2>
          <div className="mt-1 flex flex-wrap items-center gap-1.5">
            <Badge variant={recommendation ? "ok" : "muted"}>
              Confidence {confidence}%
            </Badge>
            <span className="truncate text-[10px] text-content-tertiary">
              {recommendation
                ? `B-tree · ${recommendation.target_table} (${columns})`
                : "Sample composite B-tree · orders"}
            </span>
          </div>
        </div>
        <Button
          variant="ghost"
          aria-label="Copy the migration script"
          title="Copy the migration script"
          onClick={copySql}
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
              <span className="text-content-primary">{sql}</span>
            </code>
          </pre>

          <p className="py-2 text-center text-[10px] text-content-disabled">
            {recommendation
              ? `Write amplification +${recommendation.write_impact_percentage.toFixed(1)}% · storage +${formatBytes(recommendation.storage_overhead_bytes)}`
              : "Write amplification +2.1% · storage +0.4%"}
          </p>
        </div>
      </ScrollArea>

      <div className="shrink-0 space-y-1.5 px-4 pb-2.5 pt-1.5">
        <Button
          variant="primary"
          className="w-full"
          onClick={applied ? revert : apply}
          disabled={busy}
          aria-busy={busy}
        >
          {busy ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
          ) : applied ? (
            <RotateCcw className="h-3.5 w-3.5" aria-hidden />
          ) : (
            <Database className="h-3.5 w-3.5" aria-hidden />
          )}
          {status === "applying"
            ? "Applying…"
            : status === "reverting"
              ? "Reverting…"
              : applied
                ? "Revert in Shadow DB"
                : "Apply to Shadow DB"}
        </Button>
        <Button variant="secondary" className="w-full" onClick={copySql}>
          <Copy className="h-3.5 w-3.5" aria-hidden />
          Copy SQL
        </Button>
      </div>
    </div>
  );
}
