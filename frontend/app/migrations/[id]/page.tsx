"use client";

import { Suspense, use } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { AlertTriangle, ArrowRight, CheckCircle2, Database, Loader2, XCircle } from "lucide-react";
import { api } from "@/lib/api";
import { useJob } from "@/lib/use-job";
import type { CheckResult, MigrationRunStatus, TableRunStatus } from "@/lib/types";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { PageHeader } from "@/components/page-header";

const RUN_STATUS: Record<MigrationRunStatus, "secondary" | "warning" | "success" | "destructive" | "outline"> = {
  pending: "secondary", running: "warning", succeeded: "success", failed: "destructive", cancelled: "outline",
};
const TABLE_STATUS: Record<TableRunStatus, "secondary" | "warning" | "success" | "destructive" | "outline"> = {
  pending: "secondary", running: "warning", succeeded: "success", failed: "destructive", skipped: "outline",
};

// Sort priority: actively-changing rows go to the top so the user can watch them.
// Within each band tables stay alphabetical by source name.
const STATUS_PRIORITY: Record<TableRunStatus, number> = {
  running: 0,
  pending: 1,
  failed: 2,
  succeeded: 3,
  skipped: 4,
};

export default function MigrationRunPage({ params }: { params: Promise<{ id: string }> }) {
  return (
    <Suspense fallback={<p className="text-sm text-muted-foreground">Loading…</p>}>
      <MigrationRunBody params={params} />
    </Suspense>
  );
}

function MigrationRunBody({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const search = useSearchParams();
  const jobId = search.get("job");
  const job = useJob(jobId);
  const qc = useQueryClient();

  const run = useQuery({
    queryKey: ["migration-run", id],
    queryFn: () => api.getMigrationRun(id),
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      return s === "succeeded" || s === "failed" || s === "cancelled" ? false : 1500;
    },
  });

  // Pull the comparison so we can show source/dest connection names. Reuses the same
  // ["comparison-report", id] cache key as the comparison detail page so it dedupes.
  const report = useQuery({
    queryKey: ["comparison-report", run.data?.comparison_id],
    queryFn: () => api.getComparisonReport(run.data!.comparison_id),
    enabled: !!run.data?.comparison_id,
    staleTime: 60_000,
  });

  const cancel = useMutation({
    mutationFn: () => api.cancelMigrationRun(id),
    onSuccess: () => {
      toast.success("Cancelled");
      qc.invalidateQueries({ queryKey: ["migration-run", id] });
    },
    onError: (e) => toast.error(String(e)),
  });

  const cleanupStale = useMutation({
    mutationFn: () => api.cleanupStaleMigrationTables(id),
    onSuccess: (data) => {
      const stuckCount = data.tables.filter((t) => t.error?.startsWith("stale:")).length;
      toast.success(stuckCount > 0 ? `Marked ${stuckCount} stale table(s) as failed` : "No stale tables found");
      qc.invalidateQueries({ queryKey: ["migration-run", id] });
    },
    onError: (e) => toast.error(String(e)),
  });

  if (!run.data) return <p className="text-sm text-muted-foreground">Loading…</p>;

  const r = run.data;
  const sortedTables = [...r.tables].sort((a, b) => {
    const pa = STATUS_PRIORITY[a.status] ?? 99;
    const pb = STATUS_PRIORITY[b.status] ?? 99;
    if (pa !== pb) return pa - pb;
    return a.source_table.localeCompare(b.source_table);
  });
  const totalRead = r.tables.reduce((n, t) => n + (t.rows_read ?? 0), 0);
  const totalWritten = r.tables.reduce((n, t) => n + (t.rows_written ?? 0), 0);
  const counts = r.tables.reduce<Record<string, number>>((acc, t) => {
    acc[t.status] = (acc[t.status] ?? 0) + 1;
    return acc;
  }, {});
  const isActive = r.status === "running" || r.status === "pending";
  const jobErrored = job.data?.status === "complete" && !!job.data.error;

  const title = report.data
    ? `${report.data.source_connection.name} → ${report.data.dest_connection.name}`
    : "Migration run";
  const scopeLabel = report.data
    ? report.data.source_schema && report.data.dest_schema
      ? `schema ${report.data.source_schema}${report.data.source_schema !== report.data.dest_schema ? ` → ${report.data.dest_schema}` : ""}`
      : "all schemas"
    : null;

  return (
    <div>
      <PageHeader
        title={title}
        description={
          <span>
            <Badge variant={RUN_STATUS[r.status]}>{r.status}</Badge>
            {scopeLabel && <span className="ml-2 text-xs">{scopeLabel}</span>}
            <span className="font-mono text-[10px] ml-2 text-muted-foreground">run {r.id.slice(0, 8)}…</span>
          </span>
        }
        breadcrumbs={[
          { label: "Migrations", href: "/migrations" },
          { label: r.id.slice(0, 8) + "…" },
        ]}
        actions={
          <>
            <Button asChild variant="outline">
              <Link href={`/comparisons/${r.comparison_id}`}>Open comparison</Link>
            </Button>
            {isActive && (
              <Button variant="outline" onClick={() => cancel.mutate()} disabled={cancel.isPending}>
                Cancel
              </Button>
            )}
            {/* Show cleanup-stale only when the run has terminated but at least one table
                is still stuck in pending/running (worker died, mid-flight COPY, etc.). */}
            {!isActive && r.tables.some((t) => t.status === "running" || t.status === "pending") && (
              <Button
                variant="outline"
                onClick={() => {
                  if (
                    confirm(
                      "Mark all tables stuck in 'running' or 'pending' as failed? Use this when the worker died or after a cancel left tables in limbo.",
                    )
                  ) {
                    cleanupStale.mutate();
                  }
                }}
                disabled={cleanupStale.isPending}
              >
                Clean up stale tables
              </Button>
            )}
          </>
        }
      />

      {/* Source / destination panels — gives the user immediate context on what is moving where. */}
      {report.data && (
        <div className="grid grid-cols-1 md:grid-cols-[1fr_auto_1fr] gap-3 items-stretch mb-4">
          <DbPanel
            role="source"
            name={report.data.source_connection.name}
            engine={report.data.source_connection.engine}
            extra={`${report.data.source_snapshot.table_count} tables in snapshot`}
          />
          <ArrowRight className="hidden md:block h-5 w-5 text-muted-foreground self-center mx-auto" />
          <DbPanel
            role="destination"
            name={report.data.dest_connection.name}
            engine={report.data.dest_connection.engine}
            extra={`${report.data.dest_snapshot.table_count} tables in snapshot`}
          />
        </div>
      )}

      {jobErrored && (
        <Alert variant="destructive" className="mb-4">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>Worker reported a top-level failure</AlertTitle>
          <AlertDescription>
            <pre className="mt-1 whitespace-pre-wrap text-xs">{job.data!.error!}</pre>
          </AlertDescription>
        </Alert>
      )}
      {r.error && (
        <Alert variant="destructive" className="mb-4">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>Run error</AlertTitle>
          <AlertDescription>
            <pre className="mt-1 whitespace-pre-wrap text-xs">{r.error}</pre>
          </AlertDescription>
        </Alert>
      )}

      <div className="flex flex-wrap items-center gap-2 mb-4 text-sm">
        <Badge variant="outline">{r.tables.length} total</Badge>
        {counts.running > 0 && (
          <Badge variant="warning">
            <Loader2 className="h-3 w-3 mr-1 animate-spin" /> {counts.running} running
          </Badge>
        )}
        {counts.pending > 0 && <Badge variant="secondary">{counts.pending} pending</Badge>}
        {counts.succeeded > 0 && <Badge variant="success">{counts.succeeded} succeeded</Badge>}
        {counts.failed > 0 && <Badge variant="destructive">{counts.failed} failed</Badge>}
        {counts.skipped > 0 && <Badge variant="outline">{counts.skipped} skipped</Badge>}
        <span className="text-muted-foreground">·</span>
        <Badge variant="outline">read: {totalRead.toLocaleString()}</Badge>
        <Badge variant="outline">written: {totalWritten.toLocaleString()}</Badge>
        {r.started_at && (
          <span className="text-muted-foreground text-xs">
            started {new Date(r.started_at).toLocaleString()}
          </span>
        )}
        {r.finished_at && (
          <span className="text-muted-foreground text-xs">
            · finished {new Date(r.finished_at).toLocaleString()}
          </span>
        )}
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">
            Tables — sorted by activity (running first, then pending, then completed)
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Source → Dest</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Conflict</TableHead>
                <TableHead>Rows (read → written)</TableHead>
                <TableHead>Duration</TableHead>
                <TableHead>Verification</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {sortedTables.map((t) => (
                <TableRow
                  key={t.id}
                  className={t.status === "running" ? "bg-amber-50/40 dark:bg-amber-500/5" : undefined}
                >
                  <TableCell className="font-mono text-xs">
                    {t.source_table}
                    <span className="mx-1 text-muted-foreground">→</span>
                    {t.dest_table}
                  </TableCell>
                  <TableCell>
                    <Badge variant={TABLE_STATUS[t.status]}>
                      {t.status === "running" && <Loader2 className="h-3 w-3 mr-1 animate-spin" />}
                      {t.status}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-xs">{t.conflict_mode}</TableCell>
                  <TableCell className="font-mono text-xs">
                    {(t.rows_read ?? 0).toLocaleString()}
                    <span className="mx-1 text-muted-foreground">→</span>
                    {(t.rows_written ?? 0).toLocaleString()}
                  </TableCell>
                  <TableCell className="text-xs">
                    {t.duration_ms != null ? `${(t.duration_ms / 1000).toFixed(2)}s` : "—"}
                  </TableCell>
                  <TableCell>
                    <VerificationBadges checks={t.verification} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* Per-table errors */}
      {r.tables.filter((t) => t.error).length > 0 && (
        <div className="mt-4 space-y-3">
          {r.tables
            .filter((t) => t.error)
            .map((t) => (
              <Alert key={t.id} variant="destructive">
                <AlertTriangle className="h-4 w-4" />
                <AlertTitle className="font-mono text-xs">{t.source_table} → {t.dest_table}</AlertTitle>
                <AlertDescription>
                  <pre className="mt-1 whitespace-pre-wrap text-xs">{t.error}</pre>
                </AlertDescription>
              </Alert>
            ))}
        </div>
      )}
    </div>
  );
}

function DbPanel({
  role,
  name,
  engine,
  extra,
}: {
  role: "source" | "destination";
  name: string;
  engine: string;
  extra?: string;
}) {
  return (
    <div className="border rounded-md p-3 bg-card">
      <div className="flex items-center justify-between mb-1">
        <div className="flex items-center gap-2">
          <Database className="h-4 w-4 text-muted-foreground" />
          <span className="font-medium">{name}</span>
        </div>
        <Badge variant={role === "source" ? "secondary" : "outline"} className="text-[10px]">
          {role}
        </Badge>
      </div>
      <p className="text-xs text-muted-foreground">
        {engine}
        {extra && ` · ${extra}`}
      </p>
    </div>
  );
}

function VerificationBadges({ checks }: { checks: CheckResult[] }) {
  if (!checks.length) return <span className="text-xs text-muted-foreground">—</span>;
  return (
    <div className="flex flex-wrap gap-1">
      {checks.map((c, i) => (
        <Badge
          key={i}
          variant={c.passed ? "success" : "destructive"}
          title={c.detail}
        >
          {c.passed ? <CheckCircle2 className="h-3 w-3 mr-1" /> : <XCircle className="h-3 w-3 mr-1" />}
          {c.name.replace(/_/g, " ")}
        </Badge>
      ))}
    </div>
  );
}
