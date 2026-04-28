"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { AlertTriangle, ArrowRight, ArrowRightLeft, ChevronDown, ChevronRight, FileText, Info } from "lucide-react";
import { api } from "@/lib/api";
import type {
  ConflictMode,
  MigrationFinding,
  MigrationOptionsPayload,
  MigrationPreflightResponse,
  MigrationTableOption,
  VerificationLevel,
} from "@/lib/types";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { PageHeader } from "@/components/page-header";

const CONFLICT_MODES: ConflictMode[] = ["truncate", "append", "abort"];
const VERIFICATION_LEVELS: { value: VerificationLevel; label: string }[] = [
  { value: "count_only", label: "Row count only" },
  { value: "count_and_sample", label: "Count + hash sample" },
  { value: "count_sample_and_full_hash", label: "Count + sample + full hash" },
];

// Wrapping the body in <Suspense> lets Next.js prerender a placeholder during build —
// useSearchParams() can only run client-side, so the inner body hydrates with the real
// query string. Without this, `next build` errors out with a CSR-bailout warning.
export default function NewMigrationPage() {
  return (
    <Suspense fallback={<p className="text-sm text-muted-foreground">Loading…</p>}>
      <NewMigrationPageBody />
    </Suspense>
  );
}

function NewMigrationPageBody() {
  const router = useRouter();
  const search = useSearchParams();
  const comparisonId = search.get("comparison");

  const cmpReport = useQuery({
    queryKey: ["comparison-report", comparisonId],
    queryFn: () => api.getComparisonReport(comparisonId!),
    enabled: !!comparisonId,
  });

  const [tableOptions, setTableOptions] = useState<MigrationTableOption[]>([]);
  const [defaultVerification, setDefaultVerification] = useState<VerificationLevel>("count_and_sample");
  const [preflight, setPreflight] = useState<MigrationPreflightResponse | null>(null);
  const [showDdlFor, setShowDdlFor] = useState<string | null>(null);

  // Auto-populate table options from comparison common tables when the report loads.
  useEffect(() => {
    if (!cmpReport.data) return;
    const common = cmpReport.data.diff.common_tables ?? [];
    setTableOptions(
      common.map((t) => {
        // common.table is "schema.name" or "src_schema.name → dst_schema.name" — split on " → " if present.
        const [src, dst] = t.table.includes(" → ") ? t.table.split(" → ") : [t.table, t.table];
        return {
          source_table: src.trim(),
          dest_table: dst.trim(),
          include: true,
          conflict_mode: "truncate" as ConflictMode,
          verification: "count_and_sample" as VerificationLevel,
        };
      }),
    );
  }, [cmpReport.data]);

  const skippedTables = (cmpReport.data?.diff.tables_only_in_source ?? []) as string[];

  const payload: MigrationOptionsPayload = useMemo(
    () => ({ tables: tableOptions, default_verification: defaultVerification }),
    [tableOptions, defaultVerification],
  );

  const preflightMut = useMutation({
    mutationFn: () => api.preflightMigration({ comparison_id: comparisonId!, options: payload }),
    onSuccess: (r) => setPreflight(r),
    onError: (e) => toast.error(String(e)),
  });

  const runMut = useMutation({
    mutationFn: () => api.createMigrationRun({ comparison_id: comparisonId!, options: payload }),
    onSuccess: (r) => {
      toast.success("Migration started");
      router.push(`/migrations/${r.run_id}?job=${encodeURIComponent(r.job_id)}`);
    },
    onError: (e) => toast.error(String(e)),
  });

  if (!comparisonId) {
    return (
      <div>
        <PageHeader title="New migration" description="Open this page from a comparison." />
        <p className="text-sm text-muted-foreground">
          <Link className="underline" href="/comparisons">
            Pick a comparison
          </Link>{" "}
          to plan a migration from.
        </p>
      </div>
    );
  }
  if (!cmpReport.data) return <p className="text-sm text-muted-foreground">Loading comparison…</p>;

  const r = cmpReport.data;
  const includedCount = tableOptions.filter((t) => t.include).length;
  const canRun = !!preflight?.can_run && includedCount > 0;

  const updateTable = (i: number, patch: Partial<MigrationTableOption>) =>
    setTableOptions((arr) => arr.map((o, idx) => (idx === i ? { ...o, ...patch } : o)));

  return (
    <div>
      <PageHeader
        title="New migration"
        description={
          <span>
            <strong>{r.source_connection.name}</strong> → <strong>{r.dest_connection.name}</strong>
            {" · "}
            {r.source_schema && r.dest_schema
              ? `schema ${r.source_schema}${r.source_schema !== r.dest_schema ? ` → ${r.dest_schema}` : ""}`
              : "all schemas"}
          </span>
        }
        breadcrumbs={[
          { label: "Migrations", href: "/migrations" },
          { label: "New" },
        ]}
        actions={
          <>
            <Button variant="outline" onClick={() => preflightMut.mutate()} disabled={preflightMut.isPending || !tableOptions.length}>
              {preflightMut.isPending ? "Checking…" : "Pre-flight"}
            </Button>
            <Button
              onClick={() => {
                if (!canRun) return;
                if (
                  !confirm(
                    `Run migration on ${includedCount} table(s)? Truncate-mode tables will lose existing rows on the destination.`,
                  )
                )
                  return;
                runMut.mutate();
              }}
              disabled={!canRun || runMut.isPending}
            >
              <ArrowRightLeft className="h-4 w-4" /> Run
            </Button>
          </>
        }
      />

      {/* Bulk-edit controls — applied to every row in one click. With many tables in the
          plan, clicking through individual rows is unworkable. */}
      <Card className="mb-4">
        <CardContent className="space-y-3 p-4">
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-sm font-medium w-32">Conflict mode</span>
            <Button
              size="sm"
              variant="outline"
              onClick={() => setTableOptions((arr) => arr.map((o) => ({ ...o, conflict_mode: "truncate" })))}
            >
              Truncate all
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => setTableOptions((arr) => arr.map((o) => ({ ...o, conflict_mode: "append" })))}
            >
              Append all
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => setTableOptions((arr) => arr.map((o) => ({ ...o, conflict_mode: "abort" })))}
            >
              Abort if non-empty all
            </Button>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-sm font-medium w-32">Verification</span>
            <Select value={defaultVerification} onValueChange={(v) => setDefaultVerification(v as VerificationLevel)}>
              <SelectTrigger className="w-[260px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {VERIFICATION_LEVELS.map((v) => (
                  <SelectItem key={v.value} value={v.value}>
                    {v.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button
              size="sm"
              variant="outline"
              onClick={() => setTableOptions((arr) => arr.map((o) => ({ ...o, verification: defaultVerification })))}
            >
              Apply to all
            </Button>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-sm font-medium w-32">Selection</span>
            <Button
              size="sm"
              variant="outline"
              onClick={() => setTableOptions((arr) => arr.map((o) => ({ ...o, include: true })))}
            >
              Include all
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => setTableOptions((arr) => arr.map((o) => ({ ...o, include: false })))}
            >
              Exclude all
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Common tables (the ones we'll actually migrate) */}
      <Card className="mb-4">
        <CardHeader>
          <CardTitle className="text-base">Tables to migrate</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {tableOptions.length === 0 ? (
            <p className="p-4 text-sm text-muted-foreground">
              No common tables in this comparison. Nothing to migrate.
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Include</TableHead>
                  <TableHead>Source table</TableHead>
                  <TableHead>Destination table</TableHead>
                  <TableHead>Conflict mode</TableHead>
                  <TableHead>Verification</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {tableOptions.map((t, i) => (
                  <TableRow key={`${t.source_table}→${t.dest_table}`}>
                    <TableCell>
                      <input
                        type="checkbox"
                        checked={t.include}
                        onChange={(e) => updateTable(i, { include: e.target.checked })}
                        className="h-4 w-4"
                      />
                    </TableCell>
                    <TableCell className="font-mono text-xs">{t.source_table}</TableCell>
                    <TableCell className="font-mono text-xs">{t.dest_table}</TableCell>
                    <TableCell>
                      <Select
                        value={t.conflict_mode}
                        onValueChange={(v) => updateTable(i, { conflict_mode: v as ConflictMode })}
                      >
                        <SelectTrigger className="w-[140px]">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {CONFLICT_MODES.map((m) => (
                            <SelectItem key={m} value={m}>
                              {m}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </TableCell>
                    <TableCell>
                      <Select
                        value={t.verification}
                        onValueChange={(v) => updateTable(i, { verification: v as VerificationLevel })}
                      >
                        <SelectTrigger className="w-[220px]">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {VERIFICATION_LEVELS.map((v) => (
                            <SelectItem key={v.value} value={v.value}>
                              {v.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Skipped (only-in-source) — DDL preview */}
      {skippedTables.length > 0 && (
        <Card className="mb-4">
          <CardHeader>
            <CardTitle className="text-base">Skipped — only on source</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground mb-2">
              These tables don't exist on the destination. v1 doesn't auto-create. Click <strong>Show DDL</strong> to copy
              CREATE TABLE SQL you can run on the destination yourself before retrying.
            </p>
            <ul className="space-y-1">
              {skippedTables.map((t) => (
                <li key={t} className="flex items-center justify-between gap-2 text-sm">
                  <span className="font-mono">{t}</span>
                  <Button size="sm" variant="ghost" onClick={() => setShowDdlFor(t)}>
                    <FileText className="h-3.5 w-3.5" /> Show DDL
                  </Button>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}

      {/* Preflight results */}
      {preflight && <PreflightPanel result={preflight} />}

      {/* DDL preview modal — fetched from preflight (which carries skipped_tables[].ddl_preview) */}
      <Dialog open={!!showDdlFor} onOpenChange={(o) => !o && setShowDdlFor(null)}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle className="font-mono">{showDdlFor}</DialogTitle>
            <DialogDescription>
              CREATE TABLE preview. Run this on the destination database, then re-run pre-flight.
            </DialogDescription>
          </DialogHeader>
          <DdlBlock ddl={preflight?.skipped_tables.find((s) => s.source_table === showDdlFor)?.ddl_preview ?? null} />
        </DialogContent>
      </Dialog>
    </div>
  );
}

function PreflightPanel({ result }: { result: MigrationPreflightResponse }) {
  const errs = result.findings.filter((f) => f.severity === "error");
  const warns = result.findings.filter((f) => f.severity === "warning");
  const infos = result.findings.filter((f) => f.severity === "info");

  // Total rows that would be lost if all truncate-mode warnings stand
  const totalTruncate = Object.values(result.would_truncate_counts).reduce((a, b) => a + b, 0);

  return (
    <div className="space-y-3 mb-4">
      {errs.length > 0 && (
        <CollapsibleFindings
          tone="destructive"
          icon={<AlertTriangle className="h-4 w-4" />}
          title={`Pre-flight blocked: ${errs.length} issue${errs.length === 1 ? "" : "s"}`}
          findings={errs}
          defaultOpen
        />
      )}
      {warns.length > 0 && (
        <CollapsibleFindings
          tone="warning"
          icon={<AlertTriangle className="h-4 w-4" />}
          title={
            totalTruncate > 0
              ? `${warns.length} warning${warns.length === 1 ? "" : "s"} — ~${totalTruncate.toLocaleString()} rows would be wiped on Run`
              : `${warns.length} warning${warns.length === 1 ? "" : "s"}`
          }
          findings={warns}
          summary="These tables have data on the destination. Truncate-mode will replace it with what's in the source. Switch tables to append, or skip them, to keep destination data."
        />
      )}
      {infos.length > 0 && (
        <CollapsibleFindings
          tone="default"
          icon={<Info className="h-4 w-4" />}
          title={`${infos.length} note${infos.length === 1 ? "" : "s"}`}
          findings={infos}
        />
      )}
      {result.findings.length === 0 && (
        <Alert>
          <ArrowRight className="h-4 w-4" />
          <AlertTitle>Pre-flight clean</AlertTitle>
          <AlertDescription>No issues found. Click Run to start the migration.</AlertDescription>
        </Alert>
      )}
    </div>
  );
}

function CollapsibleFindings({
  tone,
  icon,
  title,
  findings,
  summary,
  defaultOpen = false,
}: {
  tone: "destructive" | "warning" | "default";
  icon: React.ReactNode;
  title: string;
  findings: MigrationFinding[];
  summary?: string;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);

  // Group by `code` — when there are dozens of identical-kind findings (the common case
  // for "162 tables will be truncated"), this lets the user see one row per kind plus
  // a count, with details available on demand.
  const groups = findings.reduce<Record<string, MigrationFinding[]>>((acc, f) => {
    (acc[f.code] ??= []).push(f);
    return acc;
  }, {});
  const groupEntries = Object.entries(groups).sort(([, a], [, b]) => b.length - a.length);

  const variant = tone === "default" ? undefined : tone;

  return (
    <Alert variant={variant as "destructive" | "warning" | undefined}>
      {icon}
      <AlertTitle className="flex items-center justify-between gap-2">
        <span>{title}</span>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setOpen((o) => !o)}
          className="h-6"
        >
          {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
          {open ? "Hide details" : "Show details"}
        </Button>
      </AlertTitle>
      <AlertDescription className="space-y-2">
        {summary && <p>{summary}</p>}
        <ul className="text-xs space-y-0.5">
          {groupEntries.map(([code, items]) => (
            <li key={code} className="flex items-center justify-between gap-2">
              <code className="text-muted-foreground">{code}</code>
              <span className="font-medium">
                {items.length} table{items.length === 1 ? "" : "s"}
              </span>
            </li>
          ))}
        </ul>
        {open && (
          <div className="pt-2 mt-2 border-t border-current/10">
            {groupEntries.map(([code, items]) => (
              <div key={code} className="mb-3 last:mb-0">
                <p className="text-xs font-semibold mb-1">
                  <code>{code}</code> — {items.length}
                </p>
                <ul className="text-xs space-y-0.5 max-h-64 overflow-y-auto pl-2">
                  {items.map((f, i) => (
                    <li key={i} className="font-mono">
                      {f.target?.replace(/^table:/, "") ?? f.message}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        )}
      </AlertDescription>
    </Alert>
  );
}

function DdlBlock({ ddl }: { ddl: string | null }) {
  if (!ddl) return <p className="text-sm text-muted-foreground">(run Pre-flight first to populate the DDL preview)</p>;
  return (
    <pre className="overflow-auto rounded-md bg-muted p-3 text-xs font-mono whitespace-pre-wrap">{ddl}</pre>
  );
}
