import type { ComparisonReport, SchemaWarning } from "./types";
import { explain } from "./warning-explanations";

/** Build a self-contained Markdown report — suitable for pasting into a doc, attaching
 * to a ticket, or saving as a .md file. */
export function comparisonReportToMarkdown(r: ComparisonReport): string {
  const lines: string[] = [];

  lines.push(`# Schema comparison: ${r.source_connection.name} → ${r.dest_connection.name}`, "");
  lines.push(`_Generated ${new Date().toLocaleString()} from comparison \`${r.id}\` (created ${new Date(r.created_at).toLocaleString()})_`, "");

  const scope =
    r.source_schema && r.dest_schema
      ? r.source_schema === r.dest_schema
        ? `schema \`${r.source_schema}\` on both sides`
        : `schema \`${r.source_schema}\` (source) → \`${r.dest_schema}\` (destination)`
      : "all non-system schemas (whole-DB diff)";
  lines.push(`**Scope:** ${scope}`, "");

  lines.push("## Databases", "");
  lines.push(
    `| | Name | Engine | Server | Tables | Views | RLS policies | Snapshot |`,
    `|---|---|---|---|---|---|---|---|`,
    rowFor("Source", r.source_connection.name, r.source_connection.engine, r.source_snapshot),
    rowFor("Destination", r.dest_connection.name, r.dest_connection.engine, r.dest_snapshot),
    "",
  );

  const diff = r.diff;
  const driftTables = diff.common_tables.filter((t) => t.column_drift.length > 0);
  const totalDriftCols = diff.common_tables.reduce((n, t) => n + t.column_drift.length, 0);

  lines.push("## Summary", "");
  lines.push(`- **${diff.common_tables.length}** tables in both`);
  lines.push(`- **${diff.tables_only_in_source.length}** only in source (${r.source_connection.name})`);
  lines.push(`- **${diff.tables_only_in_dest.length}** only in destination (${r.dest_connection.name})`);
  lines.push(`- **${driftTables.length}** common tables have column drift (${totalDriftCols} columns)`);
  lines.push("");

  if (diff.tables_only_in_source.length) {
    lines.push(`## Only in source — ${r.source_connection.name}`, "");
    lines.push("These tables don't exist on the destination. They'll need to be created (or skipped) before data can be migrated.", "");
    diff.tables_only_in_source.forEach((t) => lines.push(`- \`${t}\``));
    lines.push("");
  }

  if (diff.tables_only_in_dest.length) {
    lines.push(`## Only in destination — ${r.dest_connection.name}`, "");
    lines.push("These tables don't exist on the source. They'll keep their data on the destination but won't receive anything new from the migration.", "");
    diff.tables_only_in_dest.forEach((t) => lines.push(`- \`${t}\``));
    lines.push("");
  }

  if (driftTables.length) {
    lines.push("## Column drift on common tables", "");
    lines.push(`Drift between \`${r.source_connection.name}\` (source) and \`${r.dest_connection.name}\` (destination).`, "");
    driftTables.forEach((tbl) => {
      lines.push(`### \`${tbl.table}\``, "");
      lines.push(`| Column | Kind | Source | Destination |`);
      lines.push(`|---|---|---|---|`);
      tbl.column_drift.forEach((d) => {
        lines.push(
          `| \`${d.column}\` | ${d.kind.replace(/_/g, " ")} | ${escape(d.source)} | ${escape(d.dest)} |`,
        );
      });
      lines.push("");
    });
  }

  lines.push(...warningsSection(`Notes on source — ${r.source_connection.name}`, r.source_snapshot.warnings));
  lines.push(...warningsSection(`Notes on destination — ${r.dest_connection.name}`, r.dest_snapshot.warnings));

  return lines.join("\n");
}

function rowFor(role: string, name: string, engine: string, snap: ComparisonReport["source_snapshot"]): string {
  return `| ${role} | ${name} | ${engine} | ${snap.server_version ?? "—"} | ${snap.table_count} | ${snap.view_count} | ${snap.rls_policy_count} | ${new Date(snap.captured_at).toLocaleString()} |`;
}

function warningsSection(title: string, warnings: SchemaWarning[]): string[] {
  if (!warnings.length) return [];
  const out: string[] = [];
  out.push(`## ${title}`, "");
  warnings.forEach((w) => {
    const tag = w.severity.toUpperCase();
    const target = w.target ? ` _(${w.target})_` : "";
    out.push(`### [${tag}] ${w.code}${target}`, "");
    out.push(w.message, "");
    const guidance = explain(w.code);
    if (guidance) {
      out.push(`> **What this means for migration:** ${guidance}`, "");
    }
  });
  return out;
}

function escape(v: string | null): string {
  if (v == null) return "";
  return v.replace(/\|/g, "\\|").replace(/\n/g, " ");
}
