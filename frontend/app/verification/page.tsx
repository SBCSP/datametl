"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import type { VerificationRunStatus } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { PageHeader } from "@/components/page-header";

const STATUS: Record<VerificationRunStatus, "secondary" | "warning" | "success" | "destructive" | "outline"> = {
  pending: "secondary", running: "warning", succeeded: "success", failed: "destructive", cancelled: "outline",
};

export default function VerificationListPage() {
  const { data, isLoading } = useQuery({
    queryKey: ["verification-runs"],
    queryFn: api.listVerificationRuns,
    refetchInterval: 5_000,
  });

  return (
    <div>
      <PageHeader
        title="Verification"
        description="Standalone parity audits — read-only on both source and destination. Use this to confirm an existing migration is still in sync, or check a destination loaded by another tool."
      />

      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : !data?.length ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16 text-center space-y-3">
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-muted">
              <ShieldCheck className="h-6 w-6 text-muted-foreground" />
            </div>
            <div>
              <h3 className="text-base font-semibold">No verification runs yet</h3>
              <p className="text-sm text-muted-foreground mt-1 max-w-sm">
                Open a comparison and click <strong>Verify</strong> to start a parity audit.
              </p>
            </div>
            <Button asChild variant="outline">
              <Link href="/comparisons">Go to comparisons</Link>
            </Button>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Run</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Tables</TableHead>
                  <TableHead>Pass / Fail</TableHead>
                  <TableHead>Started</TableHead>
                  <TableHead></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.map((r) => (
                  <TableRow key={r.id}>
                    <TableCell className="font-mono text-xs">{r.id.slice(0, 8)}…</TableCell>
                    <TableCell>
                      <Badge variant={STATUS[r.status]}>{r.status}</Badge>
                    </TableCell>
                    <TableCell>{r.table_count}</TableCell>
                    <TableCell className="text-xs">
                      <Badge variant="success" className="mr-1">{r.pass_count}</Badge>
                      {r.fail_count > 0 ? <Badge variant="destructive">{r.fail_count}</Badge> : null}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {r.started_at ? new Date(r.started_at).toLocaleString() : "—"}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button size="sm" variant="outline" asChild>
                        <Link href={`/verification/${r.id}`}>Open</Link>
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
