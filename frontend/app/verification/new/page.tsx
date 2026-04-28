"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import type {
  VerificationLevel,
  VerificationOptionsPayload,
  VerificationTableOption,
} from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { PageHeader } from "@/components/page-header";

const LEVELS: { value: VerificationLevel; label: string }[] = [
  { value: "count_only", label: "Row count + sequences only (fast)" },
  { value: "count_and_sample", label: "Count + hash sample (recommended)" },
  { value: "count_sample_and_full_hash", label: "Count + sample + full hash (v1.5 — falls back to sample)" },
];

export default function NewVerificationPage() {
  return (
    <Suspense fallback={<p className="text-sm text-muted-foreground">Loading…</p>}>
      <NewVerificationPageBody />
    </Suspense>
  );
}

function NewVerificationPageBody() {
  const router = useRouter();
  const search = useSearchParams();
  const comparisonId = search.get("comparison");

  const cmpReport = useQuery({
    queryKey: ["comparison-report", comparisonId],
    queryFn: () => api.getComparisonReport(comparisonId!),
    enabled: !!comparisonId,
  });

  const [tableOptions, setTableOptions] = useState<VerificationTableOption[]>([]);
  const [defaultLevel, setDefaultLevel] = useState<VerificationLevel>("count_and_sample");

  useEffect(() => {
    if (!cmpReport.data) return;
    const common = cmpReport.data.diff.common_tables ?? [];
    setTableOptions(
      common.map((t) => {
        const [src, dst] = t.table.includes(" → ") ? t.table.split(" → ") : [t.table, t.table];
        return {
          source_table: src.trim(),
          dest_table: dst.trim(),
          include: true,
          level: "count_and_sample" as VerificationLevel,
        };
      }),
    );
  }, [cmpReport.data]);

  const payload: VerificationOptionsPayload = useMemo(
    () => ({ tables: tableOptions, default_level: defaultLevel }),
    [tableOptions, defaultLevel],
  );

  const run = useMutation({
    mutationFn: () =>
      api.createVerificationRun({ comparison_id: comparisonId!, options: payload }),
    onSuccess: (r) => {
      toast.success("Verification started");
      router.push(`/verification/${r.run_id}?job=${encodeURIComponent(r.job_id)}`);
    },
    onError: (e) => toast.error(String(e)),
  });

  const updateTable = (i: number, patch: Partial<VerificationTableOption>) =>
    setTableOptions((arr) => arr.map((o, idx) => (idx === i ? { ...o, ...patch } : o)));

  const includedCount = tableOptions.filter((t) => t.include).length;

  if (!comparisonId)
    return (
      <div>
        <PageHeader title="New verification" description="Open this page from a comparison." />
        <p className="text-sm text-muted-foreground">
          <Link className="underline" href="/comparisons">
            Pick a comparison
          </Link>{" "}
          to start a verification from.
        </p>
      </div>
    );
  if (!cmpReport.data) return <p className="text-sm text-muted-foreground">Loading comparison…</p>;

  const r = cmpReport.data;

  return (
    <div>
      <PageHeader
        title="New verification"
        description={
          <span>
            <strong>{r.source_connection.name}</strong> → <strong>{r.dest_connection.name}</strong>
            {" · "}
            {r.source_schema && r.dest_schema
              ? `schema ${r.source_schema}${r.source_schema !== r.dest_schema ? ` → ${r.dest_schema}` : ""}`
              : "all schemas"}
            {" · "}
            <span className="text-emerald-700 dark:text-emerald-400">read-only on both databases</span>
          </span>
        }
        breadcrumbs={[
          { label: "Verification", href: "/verification" },
          { label: "New" },
        ]}
        actions={
          <Button onClick={() => run.mutate()} disabled={includedCount === 0 || run.isPending}>
            <ShieldCheck className="h-4 w-4" /> Run verification
          </Button>
        }
      />

      {/* Bulk controls */}
      <Card className="mb-4">
        <CardContent className="space-y-3 p-4">
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-sm font-medium w-32">Verification level</span>
            <Select value={defaultLevel} onValueChange={(v) => setDefaultLevel(v as VerificationLevel)}>
              <SelectTrigger className="w-[320px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {LEVELS.map((l) => (
                  <SelectItem key={l.value} value={l.value}>
                    {l.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button
              size="sm"
              variant="outline"
              onClick={() => setTableOptions((arr) => arr.map((o) => ({ ...o, level: defaultLevel })))}
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

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Tables ({includedCount} selected)</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {tableOptions.length === 0 ? (
            <p className="p-4 text-sm text-muted-foreground">
              No common tables in this comparison. Verification runs against tables that exist on both sides.
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Include</TableHead>
                  <TableHead>Source table</TableHead>
                  <TableHead>Destination table</TableHead>
                  <TableHead>Level</TableHead>
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
                        value={t.level}
                        onValueChange={(v) => updateTable(i, { level: v as VerificationLevel })}
                      >
                        <SelectTrigger className="w-[280px]">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {LEVELS.map((l) => (
                            <SelectItem key={l.value} value={l.value}>
                              {l.label}
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
    </div>
  );
}
