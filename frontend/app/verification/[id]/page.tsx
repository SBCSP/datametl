"use client";

import { use } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { AlertTriangle, CheckCircle2, Loader2, XCircle } from "lucide-react";
import { api } from "@/lib/api";
import { useJob } from "@/lib/use-job";
import type { CheckResult, VerificationRunStatus, VerificationTableStatus } from "@/lib/types";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { PageHeader } from "@/components/page-header";

const RUN: Record<VerificationRunStatus, "secondary" | "warning" | "success" | "destructive" | "outline"> = {
  pending: "secondary", running: "warning", succeeded: "success", failed: "destructive", cancelled: "outline",
};
const TBL: Record<VerificationTableStatus, "secondary" | "warning" | "success" | "destructive" | "outline"> = {
  pending: "secondary", running: "warning", passed: "success", failed: "destructive", skipped: "outline",
};

export default function VerificationRunPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const search = useSearchParams();
  const job = useJob(search.get("job"));
  const qc = useQueryClient();

  const run = useQuery({
    queryKey: ["verification-run", id],
    queryFn: () => api.getVerificationRun(id),
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      return s === "succeeded" || s === "failed" || s === "cancelled" ? false : 1500;
    },
  });

  const cancel = useMutation({
    mutationFn: () => api.cancelVerificationRun(id),
    onSuccess: () => {
      toast.success("Cancelled");
      qc.invalidateQueries({ queryKey: ["verification-run", id] });
    },
    onError: (e) => toast.error(String(e)),
  });

  if (!run.data) return <p className="text-sm text-muted-foreground">Loading…</p>;
  const r = run.data;
  const tables = r.tables;
  const passes = tables.filter((t) => t.status === "passed").length;
  const fails = tables.filter((t) => t.status === "failed").length;
  const isActive = r.status === "running" || r.status === "pending";
  const jobErrored = job.data?.status === "complete" && !!job.data.error;

  return (
    <div>
      <PageHeader
        title="Verification run"
        description={
          <span>
            <Badge variant={RUN[r.status]}>{r.status}</Badge>{" "}
            <span className="font-mono text-xs ml-2">{r.id}</span>
          </span>
        }
        breadcrumbs={[
          { label: "Verification", href: "/verification" },
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
          </>
        }
      />

      {jobErrored && (
        <Alert variant="destructive" className="mb-4">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>Worker failure</AlertTitle>
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
        <Badge variant="outline">{tables.length} table{tables.length === 1 ? "" : "s"}</Badge>
        <Badge variant="success">{passes} passed</Badge>
        {fails > 0 && <Badge variant="destructive">{fails} failed</Badge>}
        {r.started_at && (
          <span className="text-muted-foreground">
            started {new Date(r.started_at).toLocaleString()}
          </span>
        )}
        {r.finished_at && (
          <span className="text-muted-foreground">
            · finished {new Date(r.finished_at).toLocaleString()}
          </span>
        )}
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Per-table results</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Source → Dest</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Level</TableHead>
                <TableHead>Checks</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {tables.map((t) => (
                <TableRow key={t.id}>
                  <TableCell className="font-mono text-xs">
                    {t.source_table}
                    <span className="mx-1 text-muted-foreground">→</span>
                    {t.dest_table}
                  </TableCell>
                  <TableCell>
                    <Badge variant={TBL[t.status]}>
                      {t.status === "running" && <Loader2 className="h-3 w-3 mr-1 animate-spin" />}
                      {t.status}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-xs">{t.level}</TableCell>
                  <TableCell>
                    <CheckBadges checks={t.results} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {tables.filter((t) => t.error).length > 0 && (
        <div className="mt-4 space-y-3">
          {tables
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

function CheckBadges({ checks }: { checks: CheckResult[] }) {
  if (!checks.length) return <span className="text-xs text-muted-foreground">—</span>;
  return (
    <div className="flex flex-wrap gap-1">
      {checks.map((c, i) => (
        <Badge key={i} variant={c.passed ? "success" : "destructive"} title={c.detail}>
          {c.passed ? <CheckCircle2 className="h-3 w-3 mr-1" /> : <XCircle className="h-3 w-3 mr-1" />}
          {c.name.replace(/_/g, " ")}
        </Badge>
      ))}
    </div>
  );
}
