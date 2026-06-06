"use client";

import Link from "next/link";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { Database, Loader2, RefreshCw, Workflow } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { envStyle } from "@/lib/environments";
import type { SnapshotSummary } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { PageHeader } from "@/components/page-header";

export default function SchemasIndexPage() {
  const router = useRouter();
  const qc = useQueryClient();

  const connections = useQuery({ queryKey: ["connections"], queryFn: api.listConnections });

  // Per-connection snapshot fetch. N+1 queries — fine at Phase 1 scale; can be collapsed into a
  // single backend endpoint later if connection counts get large.
  const snapshotQueries = useQueries({
    queries: (connections.data ?? []).map((c) => ({
      queryKey: ["snapshots", c.id],
      queryFn: () => api.listSnapshots(c.id),
      staleTime: 5_000,
      refetchInterval: 5_000,
    })),
  });

  const snapshotsByConn = new Map<string, SnapshotSummary[]>();
  (connections.data ?? []).forEach((c, i) => {
    const data = snapshotQueries[i]?.data;
    if (data) snapshotsByConn.set(c.id, data);
  });

  const introspect = useMutation({
    mutationFn: (id: string) => api.introspect(id),
    onSuccess: (r, id) => {
      toast.success("Introspection started");
      qc.invalidateQueries({ queryKey: ["snapshots", id] });
      router.push(`/schemas/${id}?job=${encodeURIComponent(r.job_id)}`);
    },
    onError: (e) => toast.error(String(e)),
  });

  return (
    <div>
      <PageHeader
        title="Schemas"
        description="Each connection's latest snapshot at a glance. Click Introspect to capture or refresh."
      />

      {connections.isLoading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : !connections.data?.length ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16 text-center space-y-3">
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-muted">
              <Workflow className="h-6 w-6 text-muted-foreground" />
            </div>
            <p className="text-sm text-muted-foreground">Add a connection first.</p>
            <Button asChild>
              <Link href="/connections/new">New connection</Link>
            </Button>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Connection</TableHead>
                  <TableHead>Engine</TableHead>
                  <TableHead>Latest snapshot</TableHead>
                  <TableHead className="text-right">Tables</TableHead>
                  <TableHead className="text-right">Warnings</TableHead>
                  <TableHead className="text-right">Snapshots</TableHead>
                  <TableHead className="w-0" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {connections.data.map((c) => {
                  const snaps = snapshotsByConn.get(c.id);
                  const latest = snaps?.[0];
                  const env = envStyle(c.environment);
                  return (
                    <TableRow key={c.id} className={cn(env && `border-l-2 ${env.border}`)}>
                      <TableCell className="font-medium">
                        <Link href={`/schemas/${c.id}`} className="hover:underline">
                          {c.name}
                        </Link>
                        {env && (
                          <Badge variant="outline" className={cn("ml-2 align-middle", env.badge)}>
                            <span className={cn("h-1.5 w-1.5 rounded-full", env.dot)} />
                            {env.label}
                          </Badge>
                        )}
                      </TableCell>
                      <TableCell>
                        <Badge variant="secondary">{c.engine}</Badge>
                      </TableCell>
                      <TableCell className="text-muted-foreground whitespace-nowrap text-sm">
                        {!snaps ? (
                          "Loading…"
                        ) : latest ? (
                          new Date(latest.captured_at).toLocaleString()
                        ) : (
                          <span className="inline-flex items-center gap-1.5">
                            <Database className="h-3.5 w-3.5" /> Never introspected
                          </span>
                        )}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {latest ? latest.table_count : "—"}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {!latest ? (
                          "—"
                        ) : latest.warning_count > 0 ? (
                          <span className="text-amber-600 dark:text-amber-500">{latest.warning_count}</span>
                        ) : (
                          0
                        )}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">{snaps?.length ?? "—"}</TableCell>
                      <TableCell className="text-right whitespace-nowrap">
                        <Button variant="ghost" size="sm" asChild>
                          <Link href={`/schemas/${c.id}`}>Open</Link>
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => introspect.mutate(c.id)}
                          disabled={introspect.isPending}
                          title={latest ? "Re-introspect" : "Introspect"}
                        >
                          {introspect.isPending ? (
                            <Loader2 className="h-3.5 w-3.5 animate-spin" />
                          ) : (
                            <RefreshCw className="h-3.5 w-3.5" />
                          )}
                          {latest ? "Refresh" : "Introspect"}
                        </Button>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
