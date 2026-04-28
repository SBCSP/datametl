"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ArrowRightLeft } from "lucide-react";
import { api } from "@/lib/api";
import type { MigrationRunStatus } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { PageHeader } from "@/components/page-header";

const STATUS_VARIANT: Record<MigrationRunStatus, "secondary" | "warning" | "success" | "destructive" | "outline"> = {
  pending: "secondary",
  running: "warning",
  succeeded: "success",
  failed: "destructive",
  cancelled: "outline",
};

export default function MigrationsPage() {
  const { data, isLoading } = useQuery({
    queryKey: ["migration-runs"],
    queryFn: api.listMigrationRuns,
    refetchInterval: 5_000,
  });

  return (
    <div>
      <PageHeader
        title="Migrations"
        description="Each run is a single execution of a comparison's migration plan. Run history is retained."
      />

      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : !data?.length ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16 text-center space-y-3">
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-muted">
              <ArrowRightLeft className="h-6 w-6 text-muted-foreground" />
            </div>
            <div>
              <h3 className="text-base font-semibold">No migration runs yet</h3>
              <p className="text-sm text-muted-foreground mt-1 max-w-sm">
                Open a comparison and click <strong>Migrate</strong> to plan one.
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
                  <TableHead>Started</TableHead>
                  <TableHead>Finished</TableHead>
                  <TableHead></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.map((r) => (
                  <TableRow key={r.id}>
                    <TableCell className="font-mono text-xs">{r.id.slice(0, 8)}…</TableCell>
                    <TableCell>
                      <Badge variant={STATUS_VARIANT[r.status]}>{r.status}</Badge>
                    </TableCell>
                    <TableCell>{r.table_count}</TableCell>
                    <TableCell className="text-muted-foreground">
                      {r.started_at ? new Date(r.started_at).toLocaleString() : "—"}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {r.finished_at ? new Date(r.finished_at).toLocaleString() : "—"}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button size="sm" variant="outline" asChild>
                        <Link href={`/migrations/${r.id}`}>Open</Link>
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
