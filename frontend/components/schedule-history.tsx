"use client";

import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Loader2, XCircle } from "lucide-react";
import { api } from "@/lib/api";
import type { ScheduledRun } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

const STATUS_VARIANT: Record<string, "success" | "destructive" | "secondary" | "outline"> = {
  succeeded: "success",
  partial: "outline",
  failed: "destructive",
  running: "secondary",
};

export function RunHistoryDialog({
  scheduleId,
  open,
  onOpenChange,
  title,
}: {
  scheduleId: string;
  open: boolean;
  onOpenChange: (v: boolean) => void;
  title: string;
}) {
  // Poll while the dialog is open so a freshly-queued "Run now" shows up and progresses.
  const runs = useQuery({
    queryKey: ["schedule-runs", scheduleId],
    queryFn: () => api.getScheduleRuns(scheduleId),
    enabled: open,
    refetchInterval: open ? 3000 : false,
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Run history — {title}</DialogTitle>
          <DialogDescription>
            The most recent scheduled runs and what each connection returned.
          </DialogDescription>
        </DialogHeader>

        <div className="max-h-[60vh] space-y-3 overflow-y-auto">
          {runs.isLoading ? (
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" /> Loading…
            </p>
          ) : !runs.data?.length ? (
            <p className="text-sm text-muted-foreground">
              No runs yet. Use “Run now”, or wait for the next scheduled time.
            </p>
          ) : (
            runs.data.map((run) => <RunRow key={run.id} run={run} />)
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

function RunRow({ run }: { run: ScheduledRun }) {
  return (
    <div className="rounded-md border p-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium tabular-nums">
          {new Date(run.started_at).toLocaleString()}
        </span>
        <Badge variant={STATUS_VARIANT[run.status] ?? "outline"}>{run.status}</Badge>
      </div>

      {run.error && (
        <p className="mt-1.5 font-mono text-xs text-destructive">{run.error}</p>
      )}

      {run.summary.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-2">
          {run.summary.map((c, i) => (
            <span
              key={i}
              className="inline-flex items-center gap-1.5 rounded-md bg-muted px-2 py-1 text-xs"
              title={c.error ?? undefined}
            >
              {c.ok ? (
                <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />
              ) : (
                <XCircle className="h-3.5 w-3.5 text-destructive" />
              )}
              <span className="font-medium">{c.connection_name ?? "(connection)"}</span>
              <span className="text-muted-foreground">
                {c.ok ? `${c.row_total} row${c.row_total === 1 ? "" : "s"}` : c.error ?? "error"}
              </span>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
