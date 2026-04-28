"use client";

import Link from "next/link";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { Database, RefreshCw, Workflow } from "lucide-react";
import { api } from "@/lib/api";
import type { Connection, SnapshotSummary } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { PageHeader } from "@/components/page-header";

export default function SchemasIndexPage() {
  const router = useRouter();
  const qc = useQueryClient();

  const connections = useQuery({ queryKey: ["connections"], queryFn: api.listConnections });

  // Per-connection latest-snapshot fetch. N+1 queries — fine at Phase 1 scale; can be
  // collapsed into a single backend endpoint later if connection counts get large.
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
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
          {connections.data.map((c) => (
            <ConnectionCard
              key={c.id}
              conn={c}
              snapshots={snapshotsByConn.get(c.id)}
              onIntrospect={() => introspect.mutate(c.id)}
              busy={introspect.isPending}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function ConnectionCard({
  conn,
  snapshots,
  onIntrospect,
  busy,
}: {
  conn: Connection;
  snapshots: SnapshotSummary[] | undefined;
  onIntrospect: () => void;
  busy: boolean;
}) {
  const latest = snapshots?.[0];
  return (
    <Card className="hover:border-foreground/20 transition-colors">
      <CardContent className="p-4 space-y-3">
        <div className="flex items-center justify-between gap-2">
          <Link href={`/schemas/${conn.id}`} className="font-medium hover:underline truncate">
            {conn.name}
          </Link>
          <Badge variant="secondary">{conn.engine}</Badge>
        </div>

        <div className="text-xs space-y-1">
          {!snapshots ? (
            <span className="text-muted-foreground">Loading snapshots…</span>
          ) : latest ? (
            <>
              <div className="flex items-center gap-2">
                <Badge variant="success">snapshot</Badge>
                <span className="text-muted-foreground">
                  {new Date(latest.captured_at).toLocaleString()}
                </span>
              </div>
              <div className="text-muted-foreground">
                {latest.table_count} tables
                {latest.warning_count > 0 && ` · ${latest.warning_count} warnings`}
                {snapshots.length > 1 && ` · ${snapshots.length} total snapshots`}
              </div>
            </>
          ) : (
            <div className="flex items-center gap-2 text-muted-foreground">
              <Database className="h-3 w-3" />
              <span>Never introspected</span>
            </div>
          )}
        </div>

        <div className="flex items-center justify-between gap-2 pt-1">
          <Button variant="outline" size="sm" asChild>
            <Link href={`/schemas/${conn.id}`}>View schema</Link>
          </Button>
          <Button size="sm" onClick={onIntrospect} disabled={busy}>
            <RefreshCw className="h-3.5 w-3.5" />
            {latest ? "Refresh" : "Introspect"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
