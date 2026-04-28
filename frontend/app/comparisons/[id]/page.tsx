"use client";

import { Suspense, use, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, Database, FileText, Loader2, ShieldCheck, Truck } from "lucide-react";
import { api } from "@/lib/api";
import { useJob } from "@/lib/use-job";
import type { ColumnDrift, ComparisonReport, SchemaDiff, SchemaWarning, TableComparison } from "@/lib/types";
import { explain } from "@/lib/warning-explanations";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { PageHeader } from "@/components/page-header";

export default function ComparisonDetailPage({ params }: { params: Promise<{ id: string }> }) {
  return (
    <Suspense fallback={<p className="text-sm text-muted-foreground">Loading…</p>}>
      <ComparisonDetailBody params={params} />
    </Suspense>
  );
}

function ComparisonDetailBody({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const search = useSearchParams();
  const jobId = search.get("job");
  const job = useJob(jobId);

  const report = useQuery({
    queryKey: ["comparison-report", id],
    queryFn: () => api.getComparisonReport(id),
    refetchInterval: (q) => {
      const diff = q.state.data?.diff;
      const ready =
        diff &&
        (Array.isArray(diff.tables_only_in_source) ||
          Array.isArray(diff.tables_only_in_dest) ||
          Array.isArray(diff.common_tables));
      return ready ? false : 1500;
    },
  });

  const [openTable, setOpenTable] = useState<TableComparison | null>(null);

  const r = report.data;
  const diff = r?.diff;
  const ready =
    !!diff &&
    (Array.isArray(diff.tables_only_in_source) ||
      Array.isArray(diff.tables_only_in_dest) ||
      Array.isArray(diff.common_tables));
  const jobErrored = job.data?.status === "complete" && !!job.data.error;

  const scope =
    r?.source_schema && r?.dest_schema
      ? `schema ${r.source_schema}${r.source_schema === r.dest_schema ? "" : ` → ${r.dest_schema}`}`
      : "all schemas";

  const title = r ? `${r.source_connection.name} → ${r.dest_connection.name}` : "Comparison";

  return (
    <div>
      <PageHeader
        title={title}
        description={
          r ? (
            <span className="font-mono text-xs">
              {r.source_connection.engine} · {r.source_snapshot.table_count} tables
              <span className="mx-2 text-muted-foreground">→</span>
              {r.dest_connection.engine} · {r.dest_snapshot.table_count} tables
              <span className="mx-2 text-muted-foreground">·</span>
              <span className="text-foreground">{scope}</span>
            </span>
          ) : (
            <span className="font-mono text-xs">{id}</span>
          )
        }
        breadcrumbs={[{ label: "Comparisons", href: "/comparisons" }, { label: id.slice(0, 8) + "…" }]}
        actions={
          <>
            <Button asChild variant="outline" disabled={!ready}>
              <Link href={`/comparisons/${id}/report`} target="_blank">
                <FileText className="h-4 w-4" /> Report
              </Link>
            </Button>
            <Button asChild variant="outline" disabled={!ready}>
              <Link href={`/mappings/${id}`}>Mappings</Link>
            </Button>
            <Button asChild variant="outline" disabled={!ready}>
              <Link href={`/verification/new?comparison=${id}`}>
                <ShieldCheck className="h-4 w-4" /> Verify
              </Link>
            </Button>
            <Button asChild disabled={!ready}>
              <Link href={`/migrations/new?comparison=${id}`}>
                <Truck className="h-4 w-4" /> Migrate
              </Link>
            </Button>
          </>
        }
      />

      {!ready && !jobErrored && (
        <Alert>
          <Loader2 className="h-4 w-4 animate-spin" />
          <AlertTitle>Computing diff</AlertTitle>
          <AlertDescription>
            Worker is comparing the two snapshots and seeding default mappings.
          </AlertDescription>
        </Alert>
      )}

      {jobErrored && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>Comparison failed</AlertTitle>
          <AlertDescription>
            <pre className="mt-1 whitespace-pre-wrap text-xs">{job.data!.error!}</pre>
          </AlertDescription>
        </Alert>
      )}

      {ready && r && diff && (
        <>
          <DatabaseSummary report={r} />
          <SummaryStats diff={diff} />

          <div className="grid grid-cols-1 gap-4 md:grid-cols-3 mb-6">
            <TableListCard
              title={`Only in ${r.source_connection.name}`}
              hint="(source)"
              items={diff.tables_only_in_source}
              tone="warning"
            />
            <CommonTablesCard tables={diff.common_tables} onOpenTable={setOpenTable} />
            <TableListCard
              title={`Only in ${r.dest_connection.name}`}
              hint="(destination)"
              items={diff.tables_only_in_dest}
              tone="warning"
            />
          </div>

          <WarningsBlock
            title={`Notes & warnings on source: ${r.source_connection.name}`}
            warnings={r.source_snapshot.warnings}
          />
          <WarningsBlock
            title={`Notes & warnings on destination: ${r.dest_connection.name}`}
            warnings={r.dest_snapshot.warnings}
          />
        </>
      )}

      <Dialog open={!!openTable} onOpenChange={(o) => !o && setOpenTable(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="font-mono">{openTable?.table}</DialogTitle>
            <DialogDescription>Column-level drift</DialogDescription>
          </DialogHeader>
          {openTable && (
            <DriftTable
              drift={openTable.column_drift}
              sourceLabel={r?.source_connection.name ?? "source"}
              destLabel={r?.dest_connection.name ?? "destination"}
            />
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

function DatabaseSummary({ report }: { report: ComparisonReport }) {
  const s = report.source_snapshot;
  const d = report.dest_snapshot;
  return (
    <div className="grid grid-cols-1 md:grid-cols-[1fr_auto_1fr] gap-3 items-center mb-6">
      <DbCard role="source" name={report.source_connection.name} engine={report.source_connection.engine} snap={s} />
      <ArrowRight className="hidden md:block h-5 w-5 text-muted-foreground mx-auto" />
      <DbCard role="dest" name={report.dest_connection.name} engine={report.dest_connection.engine} snap={d} />
    </div>
  );
}

function DbCard({
  role,
  name,
  engine,
  snap,
}: {
  role: "source" | "dest";
  name: string;
  engine: string;
  snap: { server_version: string | null; table_count: number; view_count: number; rls_policy_count: number; captured_at: string };
}) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-center justify-between mb-1">
          <div className="flex items-center gap-2">
            <Database className="h-4 w-4 text-muted-foreground" />
            <span className="font-medium">{name}</span>
          </div>
          <Badge variant={role === "source" ? "secondary" : "outline"}>{role}</Badge>
        </div>
        <p className="text-xs text-muted-foreground">
          {engine}
          {snap.server_version ? ` ${snap.server_version}` : ""} · {snap.table_count} tables · {snap.view_count} views
          {snap.rls_policy_count ? ` · ${snap.rls_policy_count} RLS policies` : ""}
        </p>
        <p className="text-xs text-muted-foreground mt-1">
          snapshot {new Date(snap.captured_at).toLocaleString()}
        </p>
      </CardContent>
    </Card>
  );
}

function SummaryStats({ diff }: { diff: SchemaDiff }) {
  const onlySrc = diff.tables_only_in_source.length;
  const onlyDst = diff.tables_only_in_dest.length;
  const common = diff.common_tables.length;
  const driftTables = diff.common_tables.filter((t) => t.column_drift.length > 0).length;
  const totalDriftCols = diff.common_tables.reduce((n, t) => n + t.column_drift.length, 0);
  return (
    <div className="flex flex-wrap items-center gap-2 mb-6 text-sm">
      <Badge variant="outline">{common} tables in both</Badge>
      <Badge variant={onlySrc ? "warning" : "outline"}>{onlySrc} only in source</Badge>
      <Badge variant={onlyDst ? "warning" : "outline"}>{onlyDst} only in destination</Badge>
      <Badge variant={driftTables ? "warning" : "success"}>
        {driftTables} table{driftTables === 1 ? "" : "s"} with drift
      </Badge>
      {totalDriftCols > 0 && <Badge variant="outline">{totalDriftCols} columns drifted</Badge>}
    </div>
  );
}

function TableListCard({
  title,
  hint,
  items,
  tone,
}: {
  title: string;
  hint?: string;
  items: string[];
  tone?: "warning";
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-medium uppercase tracking-wider text-muted-foreground">
          {title} {hint && <span className="text-xs normal-case font-normal opacity-70">{hint}</span>}
        </CardTitle>
      </CardHeader>
      <CardContent>
        {items.length === 0 ? (
          <p className="text-sm text-muted-foreground">None.</p>
        ) : (
          <ul className="space-y-1 text-sm font-mono">
            {items.map((t) => (
              <li key={t} className={tone === "warning" ? "text-amber-700 dark:text-amber-400" : ""}>
                {t}
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function CommonTablesCard({
  tables,
  onOpenTable,
}: {
  tables: TableComparison[];
  onOpenTable: (t: TableComparison) => void;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-medium uppercase tracking-wider text-muted-foreground">
          Common tables
        </CardTitle>
      </CardHeader>
      <CardContent>
        {tables.length === 0 ? (
          <p className="text-sm text-muted-foreground">None.</p>
        ) : (
          <ul className="space-y-2">
            {tables.map((t) => (
              <li key={t.table} className="flex items-center justify-between gap-2">
                <span className="font-mono text-sm truncate">{t.table}</span>
                {t.column_drift.length ? (
                  <Button variant="outline" size="sm" onClick={() => onOpenTable(t)}>
                    {t.column_drift.length} drift
                  </Button>
                ) : (
                  <Badge variant="success">match</Badge>
                )}
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function WarningsBlock({ title, warnings }: { title: string; warnings: SchemaWarning[] }) {
  if (!warnings.length) return null;
  return (
    <Card className="mb-4">
      <CardHeader className="pb-3">
        <CardTitle className="text-sm font-medium">{title}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {warnings.map((w, i) => (
          <WarningItem key={i} w={w} />
        ))}
      </CardContent>
    </Card>
  );
}

function WarningItem({ w }: { w: SchemaWarning }) {
  const tone =
    w.severity === "error" ? "destructive" : w.severity === "warning" ? "warning" : "outline";
  const guidance = explain(w.code);
  return (
    <div className="rounded-md border bg-muted/30 p-3 space-y-1.5">
      <div className="flex items-center gap-2 flex-wrap">
        <Badge variant={tone as "destructive" | "warning" | "outline"}>{w.severity}</Badge>
        <code className="text-[11px] text-muted-foreground">{w.code}</code>
        {w.target && <code className="text-[11px] text-muted-foreground">· {w.target}</code>}
      </div>
      <p className="text-sm">{w.message}</p>
      {guidance && <p className="text-xs text-muted-foreground italic">{guidance}</p>}
    </div>
  );
}

function DriftTable({
  drift,
  sourceLabel,
  destLabel,
}: {
  drift: ColumnDrift[];
  sourceLabel: string;
  destLabel: string;
}) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Column</TableHead>
          <TableHead>Kind</TableHead>
          <TableHead>{sourceLabel}</TableHead>
          <TableHead>{destLabel}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {drift.map((d, i) => (
          <TableRow key={i}>
            <TableCell className="font-mono">{d.column}</TableCell>
            <TableCell>
              <Badge variant="warning">{d.kind.replace(/_/g, " ")}</Badge>
            </TableCell>
            <TableCell className="font-mono text-xs">{d.source ?? ""}</TableCell>
            <TableCell className="font-mono text-xs">{d.dest ?? ""}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
