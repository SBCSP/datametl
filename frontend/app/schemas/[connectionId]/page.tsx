"use client";

import { Suspense, use, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { AlertTriangle, Bot, Boxes, History, Info, Loader2, RefreshCw, Database } from "lucide-react";
import Link from "next/link";
import { askMelAboutConnection, askMelAboutSchema, askMelAboutTable } from "@/lib/mel-context";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { engineLabel } from "@/lib/engines";
import { useJob } from "@/lib/use-job";
import type { JobProgress, NormalizedSchema, SchemaWarning, SnapshotSummary } from "@/lib/types";
import { ApplySchemaDialog } from "@/components/apply-schema-dialog";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { PageHeader } from "@/components/page-header";

export default function SchemaPage({ params }: { params: Promise<{ connectionId: string }> }) {
  return (
    <Suspense fallback={<p className="text-sm text-muted-foreground">Loading…</p>}>
      <SchemaPageBody params={params} />
    </Suspense>
  );
}

function SchemaPageBody({ params }: { params: Promise<{ connectionId: string }> }) {
  const { connectionId } = use(params);
  const search = useSearchParams();
  const qc = useQueryClient();

  const conn = useQuery({
    queryKey: ["connection", connectionId],
    queryFn: () => api.getConnection(connectionId),
  });

  const snaps = useQuery({
    queryKey: ["snapshots", connectionId],
    queryFn: () => api.listSnapshots(connectionId),
    // Poll faster while we don't have a snapshot yet, slow down once we do.
    refetchInterval: (q) => (q.state.data?.length ? 10_000 : 2_000),
  });

  // Track the active introspect job — populated either from ?job= (when navigated from
  // /connections) or from the local Introspect button below.
  const [activeJob, setActiveJob] = useState<string | null>(search.get("job"));
  const job = useJob(activeJob);
  // Which snapshot is being viewed (defaults to the latest; see effect below).
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // When the job finishes, refetch snapshots and follow the newest one.
  useEffect(() => {
    if (job.data?.status === "complete" && !job.data.error) {
      qc.invalidateQueries({ queryKey: ["snapshots", connectionId] });
      setActiveJob(null);
      setSelectedId(null);
    }
  }, [job.data?.status, job.data?.error, qc, connectionId]);

  const latestSnapshotId = snaps.data?.[0]?.id;
  // Default the selection to the latest snapshot (and re-default after a fresh introspect).
  useEffect(() => {
    if (!selectedId && latestSnapshotId) setSelectedId(latestSnapshotId);
  }, [selectedId, latestSnapshotId]);

  const snapshot = useQuery({
    queryKey: ["snapshot", selectedId],
    queryFn: () => api.getSnapshot(selectedId!),
    enabled: !!selectedId,
  });

  const introspectMut = useMutation({
    mutationFn: () => api.introspect(connectionId),
    onSuccess: (r) => {
      setActiveJob(r.job_id);
      toast.success("Introspection started");
      qc.invalidateQueries({ queryKey: ["snapshots", connectionId] });
    },
    onError: (e) => toast.error(String(e)),
  });

  const isRunning = !!activeJob && job.data?.status !== "complete";
  const jobErrored = job.data?.status === "complete" && !!job.data.error;
  const [applyOpen, setApplyOpen] = useState(false);

  return (
    <div>
      <PageHeader
        title={conn.data?.name ?? "…"}
        description={
          <span className="inline-flex flex-wrap items-center gap-2">
            {conn.data && (
              <Badge variant="secondary">{engineLabel(conn.data.engine)}</Badge>
            )}
            <span>
              {snaps.data?.length
                ? `Latest snapshot: ${new Date(snaps.data[0].captured_at).toLocaleString()}`
                : isRunning
                  ? "Capturing schema…"
                  : "No snapshot yet."}
            </span>
          </span>
        }
        breadcrumbs={[
          { label: "Connections", href: "/connections" },
          { label: conn.data?.name ?? "…" },
        ]}
        actions={
          <div className="flex gap-2">
            {conn.data && (
              <Button variant="outline" asChild>
                <Link href={askMelAboutConnection(conn.data.name, connectionId)}>
                  <Bot className="h-4 w-4" /> Ask Mel
                </Link>
              </Button>
            )}
            {selectedId && (
              <Button variant="outline" onClick={() => setApplyOpen(true)}>
                <Boxes className="h-4 w-4" /> Apply schema
              </Button>
            )}
            <Button onClick={() => introspectMut.mutate()} disabled={introspectMut.isPending || isRunning}>
              {isRunning ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <RefreshCw className="h-4 w-4" />
              )}
              {snaps.data?.length ? "Refresh snapshot" : "Introspect"}
            </Button>
          </div>
        }
      />

      {selectedId && (
        <ApplySchemaDialog
          snapshotId={selectedId}
          sourceConnectionId={connectionId}
          open={applyOpen}
          onOpenChange={setApplyOpen}
        />
      )}

      <div className="space-y-6">
        {isRunning && <RunningBanner status={job.data?.status} progress={job.data?.progress} />}
        {jobErrored && <ErroredBanner error={job.data!.error!} />}

        {snaps.data && snaps.data.length > 0 ? (
          <div className="grid gap-6 lg:grid-cols-[18rem_1fr]">
            <SnapshotHistory
              snapshots={snaps.data}
              selectedId={selectedId}
              latestId={latestSnapshotId}
              onSelect={setSelectedId}
            />
            <div className="min-w-0 space-y-6">
              {snapshot.data?.warnings.length ? <Warnings warnings={snapshot.data.warnings} /> : null}
              {snapshot.isLoading ? (
                <p className="text-sm text-muted-foreground">Loading snapshot…</p>
              ) : snapshot.data ? (
                <SchemaTree
                  schema={snapshot.data.normalized_schema}
                  connectionId={connectionId}
                  connectionName={conn.data?.name ?? "connection"}
                />
              ) : null}
            </div>
          </div>
        ) : !isRunning && !jobErrored ? (
          <EmptyState onIntrospect={() => introspectMut.mutate()} disabled={introspectMut.isPending} />
        ) : null}
      </div>
    </div>
  );
}

function SnapshotHistory({
  snapshots,
  selectedId,
  latestId,
  onSelect,
}: {
  snapshots: SnapshotSummary[];
  selectedId: string | null;
  latestId?: string;
  onSelect: (id: string) => void;
}) {
  return (
    <Card className="h-fit lg:sticky lg:top-4">
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-sm">
          <History className="h-4 w-4" /> Snapshots
          <span className="ml-auto text-xs font-normal text-muted-foreground">{snapshots.length}</span>
        </CardTitle>
      </CardHeader>
      <CardContent className="p-2">
        <ul className="max-h-[65vh] space-y-0.5 overflow-y-auto">
          {snapshots.map((s) => {
            const active = s.id === selectedId;
            return (
              <li key={s.id}>
                <button
                  type="button"
                  onClick={() => onSelect(s.id)}
                  className={cn(
                    "w-full rounded-md px-2.5 py-2 text-left transition-colors hover:bg-accent",
                    active && "bg-accent",
                  )}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-medium">
                      {new Date(s.captured_at).toLocaleString()}
                    </span>
                    {s.id === latestId && (
                      <Badge variant="success" className="px-1.5 py-0 text-[10px]">
                        latest
                      </Badge>
                    )}
                  </div>
                  <div className="mt-0.5 text-xs text-muted-foreground">
                    {s.table_count} table{s.table_count === 1 ? "" : "s"}
                    {s.warning_count > 0 && ` · ${s.warning_count} warning${s.warning_count === 1 ? "" : "s"}`}
                  </div>
                </button>
              </li>
            );
          })}
        </ul>
      </CardContent>
    </Card>
  );
}

function RunningBanner({ status, progress }: { status?: string; progress?: JobProgress | null }) {
  const total = progress?.total ?? 0;
  const current = progress?.current ?? 0;
  const pct = total > 0 ? Math.min(100, Math.round((current / total) * 100)) : null;
  const phase = progress?.phase === "views" ? "view" : "table";
  const done = progress?.phase === "done";

  return (
    <Alert>
      <Loader2 className="h-4 w-4 animate-spin" />
      <AlertTitle>Introspection running</AlertTitle>
      <AlertDescription>
        {progress && total > 0 && !done ? (
          <div className="space-y-2">
            <div className="flex items-center justify-between gap-3 text-sm">
              <span>
                {progress.connection ? <span className="font-medium">{progress.connection}</span> : "Reading schema"}
                {progress.schema ? <> · <span className="font-mono text-xs">{progress.schema}</span></> : null}{" "}
                {phase} <span className="tabular-nums">{current}/{total}</span>
                {progress.object ? (
                  <span className="text-muted-foreground"> ({progress.object})</span>
                ) : null}
              </span>
              {pct !== null && <span className="tabular-nums text-muted-foreground">{pct}%</span>}
            </div>
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
              <div
                className="h-full rounded-full bg-primary transition-all"
                style={{ width: `${pct ?? 0}%` }}
              />
            </div>
          </div>
        ) : (
          <>
            Worker is reading schemas, tables, columns, indexes, RLS policies, and view definitions from the
            database. On a large database this can take a while. Status: {status ?? "queued"}.
          </>
        )}
      </AlertDescription>
    </Alert>
  );
}

function ErroredBanner({ error }: { error: string }) {
  return (
    <Alert variant="destructive">
      <AlertTriangle className="h-4 w-4" />
      <AlertTitle>Introspection failed</AlertTitle>
      <AlertDescription>
        <pre className="mt-1 whitespace-pre-wrap text-xs">{error}</pre>
        <p className="mt-2 text-xs text-muted-foreground">
          Tail the worker with <code className="font-mono">docker compose -f infra/docker-compose.yml logs -f worker</code>{" "}
          for full traceback.
        </p>
      </AlertDescription>
    </Alert>
  );
}

function EmptyState({ onIntrospect, disabled }: { onIntrospect: () => void; disabled: boolean }) {
  return (
    <Card>
      <CardContent className="flex flex-col items-center justify-center py-16 text-center space-y-3">
        <div className="flex h-12 w-12 items-center justify-center rounded-full bg-muted">
          <Database className="h-6 w-6 text-muted-foreground" />
        </div>
        <div>
          <h3 className="text-base font-semibold">No snapshot yet</h3>
          <p className="text-sm text-muted-foreground mt-1 max-w-sm">
            Capture this database's schema — tables, columns, types, indexes, RLS, extensions — so you can compare
            against another database.
          </p>
        </div>
        <Button onClick={onIntrospect} disabled={disabled}>
          <RefreshCw className="h-4 w-4" /> Introspect now
        </Button>
      </CardContent>
    </Card>
  );
}

function Warnings({ warnings }: { warnings: SchemaWarning[] }) {
  const by = warnings.reduce<Record<string, SchemaWarning[]>>((acc, w) => {
    (acc[w.severity] ??= []).push(w);
    return acc;
  }, {});
  return (
    <div className="space-y-3">
      {by.warning?.length ? (
        <Alert variant="warning">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>
            {by.warning.length} warning{by.warning.length === 1 ? "" : "s"}
          </AlertTitle>
          <AlertDescription>
            <ul className="list-disc pl-4 space-y-1">
              {by.warning.map((w, i) => (
                <li key={i}>{w.message}</li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      ) : null}
      {by.info?.length ? (
        <Alert>
          <Info className="h-4 w-4" />
          <AlertTitle>
            {by.info.length} note{by.info.length === 1 ? "" : "s"}
          </AlertTitle>
          <AlertDescription>
            <ul className="list-disc pl-4 space-y-1">
              {by.info.map((w, i) => (
                <li key={i}>{w.message}</li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      ) : null}
    </div>
  );
}

function SchemaTree({
  schema,
  connectionId,
  connectionName,
}: {
  schema: NormalizedSchema;
  connectionId: string;
  connectionName: string;
}) {
  const bySchema = schema.tables.reduce<Record<string, typeof schema.tables>>((acc, t) => {
    (acc[t.schema] ??= []).push(t);
    return acc;
  }, {});
  const totalCols = schema.tables.reduce((n, t) => n + t.columns.length, 0);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <Badge variant="secondary">server {schema.server_version}</Badge>
        <Badge variant="outline">
          {schema.tables.length} table{schema.tables.length === 1 ? "" : "s"}
        </Badge>
        <Badge variant="outline">{totalCols} columns</Badge>
        {schema.views.length > 0 && (
          <Badge variant="outline">
            {schema.views.length} view{schema.views.length === 1 ? "" : "s"}
          </Badge>
        )}
        {schema.rls_policies.length > 0 && (
          <Badge variant="warning">
            {schema.rls_policies.length} RLS polic{schema.rls_policies.length === 1 ? "y" : "ies"}
          </Badge>
        )}
        {schema.extensions.length > 0 && (
          <span className="text-muted-foreground">extensions: {schema.extensions.join(", ")}</span>
        )}
      </div>

      {Object.entries(bySchema)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([s, tables]) => (
          <Card key={s}>
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-muted-foreground">
                <span>
                  {s} <span className="ml-1 text-muted-foreground/70">· {tables.length}</span>
                </span>
                <Button size="sm" variant="ghost" className="ml-auto h-7 normal-case tracking-normal" asChild>
                  <Link href={askMelAboutSchema(connectionName, connectionId, s)}>
                    <Bot className="h-3.5 w-3.5" /> Ask Mel
                  </Link>
                </Button>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-6">
              {tables.map((t) => (
                <div key={t.name}>
                  <div className="mb-2 flex flex-wrap items-center gap-2">
                    <span className="font-medium">{t.name}</span>
                    {t.rls_enabled && <Badge variant="warning">RLS</Badge>}
                    {t.row_count_estimate !== null && (
                      <span className="text-xs text-muted-foreground">
                        ~{t.row_count_estimate.toLocaleString()} rows
                      </span>
                    )}
                    <Button size="sm" variant="ghost" className="ml-auto h-7" asChild>
                      <Link href={askMelAboutTable(connectionName, connectionId, s, t.name)}>
                        <Bot className="h-3.5 w-3.5" /> Ask Mel
                      </Link>
                    </Button>
                  </div>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Column</TableHead>
                        <TableHead>Type</TableHead>
                        <TableHead>Nullable</TableHead>
                        <TableHead>Default</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {t.columns.map((c) => (
                        <TableRow key={c.name}>
                          <TableCell>
                            <span className="font-mono">{c.name}</span>
                            {c.is_primary_key && (
                              <Badge className="ml-2" variant="outline">
                                PK
                              </Badge>
                            )}
                            {c.foreign_key && (
                              <Badge className="ml-2" variant="outline">
                                → {c.foreign_key.schema}.{c.foreign_key.table}.{c.foreign_key.column}
                              </Badge>
                            )}
                          </TableCell>
                          <TableCell>
                            <span className="font-mono">{c.native_type}</span>{" "}
                            <span className="text-muted-foreground">({c.normalized_type})</span>
                          </TableCell>
                          <TableCell>{c.nullable ? "yes" : "no"}</TableCell>
                          <TableCell className="font-mono text-xs">{c.default ?? ""}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              ))}
            </CardContent>
          </Card>
        ))}
    </div>
  );
}
