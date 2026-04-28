"use client";

import { use } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Database, Download, Printer } from "lucide-react";
import { api } from "@/lib/api";
import type { ComparisonReport, SchemaWarning } from "@/lib/types";
import { comparisonReportToMarkdown } from "@/lib/comparison-markdown";
import { explain } from "@/lib/warning-explanations";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

export default function ComparisonReportPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data: report, isLoading } = useQuery({
    queryKey: ["comparison-report", id],
    queryFn: () => api.getComparisonReport(id),
  });

  if (isLoading) return <p className="text-sm text-muted-foreground">Loading report…</p>;
  if (!report) return <p className="text-sm text-muted-foreground">Report not found.</p>;

  const r = report;
  const diff = r.diff;
  const driftTables = diff.common_tables.filter((t) => t.column_drift.length > 0);
  const totalDriftCols = diff.common_tables.reduce((n, t) => n + t.column_drift.length, 0);

  const onDownloadMarkdown = () => {
    const md = comparisonReportToMarkdown(r);
    const blob = new Blob([md], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `comparison-${r.source_connection.name.replace(/\W+/g, "_")}_to_${r.dest_connection.name.replace(/\W+/g, "_")}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <article className="space-y-8">
      {/* Toolbar — hidden on print */}
      <div className="flex items-center justify-end gap-2 print:hidden">
        <Button variant="outline" size="sm" onClick={onDownloadMarkdown}>
          <Download className="h-4 w-4" /> Download Markdown
        </Button>
        <Button size="sm" onClick={() => window.print()}>
          <Printer className="h-4 w-4" /> Print / Save as PDF
        </Button>
      </div>

      {/* Title */}
      <header className="space-y-2 border-b pb-4">
        <p className="text-xs uppercase tracking-wider text-muted-foreground">Schema comparison</p>
        <h1 className="text-3xl font-semibold tracking-tight">
          {r.source_connection.name}{" "}
          <ArrowRight className="inline h-6 w-6 text-muted-foreground align-baseline" />{" "}
          {r.dest_connection.name}
        </h1>
        <p className="text-sm">
          Scope:{" "}
          {r.source_schema && r.dest_schema ? (
            <span>
              schema <code className="font-mono">{r.source_schema}</code>
              {r.source_schema !== r.dest_schema && (
                <>
                  {" "}
                  → <code className="font-mono">{r.dest_schema}</code>
                </>
              )}
            </span>
          ) : (
            <span>all non-system schemas (whole-DB diff)</span>
          )}
        </p>
        <p className="text-xs text-muted-foreground">
          Generated {new Date().toLocaleString()} · comparison{" "}
          <code className="font-mono">{r.id}</code> · created {new Date(r.created_at).toLocaleString()}
        </p>
      </header>

      {/* Database panels */}
      <section className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <DbPanel role="source" name={r.source_connection.name} engine={r.source_connection.engine} snap={r.source_snapshot} />
        <DbPanel role="destination" name={r.dest_connection.name} engine={r.dest_connection.engine} snap={r.dest_snapshot} />
      </section>

      {/* Summary */}
      <section className="space-y-3">
        <h2 className="text-xl font-semibold">Summary</h2>
        <ul className="text-sm space-y-1">
          <li>
            <strong>{diff.common_tables.length}</strong> tables in both
          </li>
          <li>
            <strong>{diff.tables_only_in_source.length}</strong> only in source ({r.source_connection.name})
          </li>
          <li>
            <strong>{diff.tables_only_in_dest.length}</strong> only in destination ({r.dest_connection.name})
          </li>
          <li>
            <strong>{driftTables.length}</strong> common table{driftTables.length === 1 ? "" : "s"} with column drift
            {totalDriftCols > 0 && <> · {totalDriftCols} columns affected</>}
          </li>
        </ul>
      </section>

      {/* Only-in lists */}
      {diff.tables_only_in_source.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-xl font-semibold">Only in source — {r.source_connection.name}</h2>
          <p className="text-sm text-muted-foreground">
            These tables don't exist on the destination. They'll need to be created (or skipped) before data can be migrated.
          </p>
          <ul className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-1 text-sm font-mono">
            {diff.tables_only_in_source.map((t) => (
              <li key={t}>· {t}</li>
            ))}
          </ul>
        </section>
      )}

      {diff.tables_only_in_dest.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-xl font-semibold">Only in destination — {r.dest_connection.name}</h2>
          <p className="text-sm text-muted-foreground">
            These tables don't exist on the source. They keep their data on the destination but receive nothing from the migration.
          </p>
          <ul className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-1 text-sm font-mono">
            {diff.tables_only_in_dest.map((t) => (
              <li key={t}>· {t}</li>
            ))}
          </ul>
        </section>
      )}

      {/* Drift detail */}
      {driftTables.length > 0 && (
        <section className="space-y-4">
          <div>
            <h2 className="text-xl font-semibold">Column drift on common tables</h2>
            <p className="text-sm text-muted-foreground">
              Drift between <code className="font-mono">{r.source_connection.name}</code> (source) and{" "}
              <code className="font-mono">{r.dest_connection.name}</code> (destination).
            </p>
          </div>
          {driftTables.map((tbl) => (
            <div key={tbl.table} className="space-y-2 break-inside-avoid">
              <h3 className="font-mono text-sm font-semibold">{tbl.table}</h3>
              <div className="border rounded-md overflow-hidden">
                <table className="w-full text-sm">
                  <thead className="bg-muted/50">
                    <tr className="text-left">
                      <th className="px-3 py-1.5 font-medium">Column</th>
                      <th className="px-3 py-1.5 font-medium">Kind</th>
                      <th className="px-3 py-1.5 font-medium">{r.source_connection.name}</th>
                      <th className="px-3 py-1.5 font-medium">{r.dest_connection.name}</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {tbl.column_drift.map((d, i) => (
                      <tr key={i}>
                        <td className="px-3 py-1.5 font-mono">{d.column}</td>
                        <td className="px-3 py-1.5">
                          <Badge variant="warning">{d.kind.replace(/_/g, " ")}</Badge>
                        </td>
                        <td className="px-3 py-1.5 font-mono text-xs">{d.source ?? ""}</td>
                        <td className="px-3 py-1.5 font-mono text-xs">{d.dest ?? ""}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
        </section>
      )}

      {/* Warnings */}
      <WarningsSection
        title={`Notes on source — ${r.source_connection.name}`}
        warnings={r.source_snapshot.warnings}
      />
      <WarningsSection
        title={`Notes on destination — ${r.dest_connection.name}`}
        warnings={r.dest_snapshot.warnings}
      />

      <footer className="text-xs text-muted-foreground border-t pt-4">
        Generated by DataMETL · introspections are read-only · this report is a static view of the snapshots taken at the times shown above.
      </footer>
    </article>
  );
}

function DbPanel({
  role,
  name,
  engine,
  snap,
}: {
  role: "source" | "destination";
  name: string;
  engine: string;
  snap: ComparisonReport["source_snapshot"];
}) {
  return (
    <div className="border rounded-md p-4">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <Database className="h-4 w-4 text-muted-foreground" />
          <span className="font-medium">{name}</span>
        </div>
        <Badge variant={role === "source" ? "secondary" : "outline"}>{role}</Badge>
      </div>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
        <dt className="text-muted-foreground">Engine</dt>
        <dd>{engine}</dd>
        <dt className="text-muted-foreground">Server</dt>
        <dd>{snap.server_version ?? "—"}</dd>
        <dt className="text-muted-foreground">Tables</dt>
        <dd>{snap.table_count}</dd>
        <dt className="text-muted-foreground">Views</dt>
        <dd>{snap.view_count}</dd>
        <dt className="text-muted-foreground">RLS policies</dt>
        <dd>{snap.rls_policy_count}</dd>
        <dt className="text-muted-foreground">Snapshot</dt>
        <dd className="text-xs">{new Date(snap.captured_at).toLocaleString()}</dd>
      </dl>
    </div>
  );
}

function WarningsSection({ title, warnings }: { title: string; warnings: SchemaWarning[] }) {
  if (!warnings.length) return null;
  return (
    <section className="space-y-3 break-inside-avoid">
      <h2 className="text-xl font-semibold">{title}</h2>
      <div className="space-y-3">
        {warnings.map((w, i) => {
          const guidance = explain(w.code);
          const tone = w.severity === "error" ? "destructive" : w.severity === "warning" ? "warning" : "outline";
          return (
            <div key={i} className="border rounded-md p-3 space-y-1.5">
              <div className="flex items-center gap-2 flex-wrap">
                <Badge variant={tone as "destructive" | "warning" | "outline"}>{w.severity}</Badge>
                <code className="text-[11px] text-muted-foreground">{w.code}</code>
                {w.target && <code className="text-[11px] text-muted-foreground">· {w.target}</code>}
              </div>
              <p className="text-sm">{w.message}</p>
              {guidance && (
                <p className="text-xs text-muted-foreground italic border-l-2 pl-2">
                  <strong className="not-italic">What this means for migration: </strong>
                  {guidance}
                </p>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
