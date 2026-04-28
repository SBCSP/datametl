"use client";

import { use, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { AlertTriangle, Info, Loader2, RefreshCw, Database } from "lucide-react";
import { api } from "@/lib/api";
import { useJob } from "@/lib/use-job";
import type { NormalizedSchema, SchemaWarning } from "@/lib/types";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { PageHeader } from "@/components/page-header";

export default function SchemaPage({ params }: { params: Promise<{ connectionId: string }> }) {
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

  // When the job finishes, refetch snapshots so the new one shows up immediately.
  useEffect(() => {
    if (job.data?.status === "complete" && !job.data.error) {
      qc.invalidateQueries({ queryKey: ["snapshots", connectionId] });
      setActiveJob(null);
    }
  }, [job.data?.status, job.data?.error, qc, connectionId]);

  const latestSnapshotId = snaps.data?.[0]?.id;
  const snapshot = useQuery({
    queryKey: ["snapshot", latestSnapshotId],
    queryFn: () => api.getSnapshot(latestSnapshotId!),
    enabled: !!latestSnapshotId,
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

  return (
    <div>
      <PageHeader
        title={conn.data?.name ?? "…"}
        description={
          snaps.data?.length
            ? `Latest snapshot: ${new Date(snaps.data[0].captured_at).toLocaleString()}`
            : isRunning
              ? "Capturing schema…"
              : "No snapshot yet."
        }
        breadcrumbs={[
          { label: "Connections", href: "/connections" },
          { label: conn.data?.name ?? "…" },
        ]}
        actions={
          <Button onClick={() => introspectMut.mutate()} disabled={introspectMut.isPending || isRunning}>
            {isRunning ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <RefreshCw className="h-4 w-4" />
            )}
            {snaps.data?.length ? "Refresh snapshot" : "Introspect"}
          </Button>
        }
      />

      <div className="space-y-6">
        {isRunning && <RunningBanner status={job.data?.status} />}
        {jobErrored && <ErroredBanner error={job.data!.error!} />}
        {snapshot.data?.warnings.length ? <Warnings warnings={snapshot.data.warnings} /> : null}

        {snapshot.data ? (
          <SchemaTree schema={snapshot.data.normalized_schema} />
        ) : !isRunning && !jobErrored ? (
          <EmptyState onIntrospect={() => introspectMut.mutate()} disabled={introspectMut.isPending} />
        ) : null}
      </div>
    </div>
  );
}

function RunningBanner({ status }: { status?: string }) {
  return (
    <Alert>
      <Loader2 className="h-4 w-4 animate-spin" />
      <AlertTitle>Introspection running</AlertTitle>
      <AlertDescription>
        Worker is reading schemas, tables, columns, indexes, RLS policies, and view definitions from the database.
        On a large Supabase project this may take 10–60 seconds. Status: {status ?? "queued"}.
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

function SchemaTree({ schema }: { schema: NormalizedSchema }) {
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
              <CardTitle className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
                {s} <span className="ml-1 text-muted-foreground/70">· {tables.length}</span>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-6">
              {tables.map((t) => (
                <div key={t.name}>
                  <div className="flex items-center gap-2 mb-2">
                    <span className="font-medium">{t.name}</span>
                    {t.rls_enabled && <Badge variant="warning">RLS</Badge>}
                    {t.row_count_estimate !== null && (
                      <span className="text-xs text-muted-foreground">
                        ~{t.row_count_estimate.toLocaleString()} rows
                      </span>
                    )}
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
