"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Database, Plus } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { envStyle } from "@/lib/environments";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { PageHeader } from "@/components/page-header";

export default function ConnectionsPage() {
  const qc = useQueryClient();
  const router = useRouter();
  const { data, isLoading } = useQuery({ queryKey: ["connections"], queryFn: api.listConnections });

  const testMut = useMutation({
    mutationFn: (id: string) => api.testConnection(id),
    onSuccess: (r) =>
      r.ok
        ? toast.success("Connection OK", { description: r.detail })
        : toast.error("Failed", { description: r.detail }),
    onError: (e) => toast.error(String(e)),
  });

  const introspectMut = useMutation({
    mutationFn: (id: string) => api.introspect(id),
    onSuccess: (r, id) => {
      toast.success("Introspection started");
      qc.invalidateQueries({ queryKey: ["snapshots", id] });
      // Send the user to the schemas page where progress and the resulting tree are visible.
      router.push(`/schemas/${id}?job=${encodeURIComponent(r.job_id)}`);
    },
    onError: (e) => toast.error(String(e)),
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => api.deleteConnection(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["connections"] }),
    onError: (e) => toast.error(String(e)),
  });

  const mcpActive = useQuery({
    queryKey: ["mcp-active"],
    queryFn: api.getActiveMcp,
    refetchInterval: 5_000,
  });
  const activeId = mcpActive.data?.connection_id ?? null;
  const mcpMut = useMutation({
    mutationFn: async (id: string | null) => {
      if (id) await api.mcpActivate(id);
      else await api.mcpDeactivate();
    },
    onSuccess: (_r, id) => {
      qc.invalidateQueries({ queryKey: ["mcp-active"] });
      toast.success(id ? "MCP connection activated — read-only" : "MCP connection deactivated");
    },
    onError: (e) => toast.error(String(e)),
  });

  return (
    <div>
      <PageHeader
        title="Connections"
        description="Source and destination databases. Credentials are encrypted at rest."
        actions={
          <Button asChild>
            <Link href="/connections/new">
              <Plus className="h-4 w-4" /> New connection
            </Link>
          </Button>
        }
      />

      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : !data?.length ? (
        <EmptyState />
      ) : (
        <Card>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Engine</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.map((c) => {
                  const env = envStyle(c.environment);
                  return (
                  <TableRow
                    key={c.id}
                    className={cn(
                      env && `border-l-2 ${env.border}`,
                      activeId === c.id && "bg-orange-500/5",
                    )}
                  >
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
                      {activeId === c.id && (
                        <Badge variant="warning" className="ml-2 align-middle">Active MCP</Badge>
                      )}
                    </TableCell>
                    <TableCell>
                      <Badge variant="secondary">{c.engine}</Badge>
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {new Date(c.created_at).toLocaleString()}
                    </TableCell>
                    <TableCell className="text-right space-x-2">
                      {activeId === c.id ? (
                        <Button
                          size="sm"
                          variant="outline"
                          className="border-orange-500/50 text-orange-600 hover:text-orange-700"
                          onClick={() => mcpMut.mutate(null)}
                          disabled={mcpMut.isPending}
                        >
                          Deactivate MCP
                        </Button>
                      ) : (
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => mcpMut.mutate(c.id)}
                          disabled={mcpMut.isPending}
                        >
                          Activate MCP
                        </Button>
                      )}
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => testMut.mutate(c.id)}
                        disabled={testMut.isPending}
                      >
                        Test
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => introspectMut.mutate(c.id)}
                        disabled={introspectMut.isPending}
                      >
                        Introspect
                      </Button>
                      <Button size="sm" variant="outline" asChild>
                        <Link href={`/connections/${c.id}/edit`}>Edit</Link>
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => {
                          if (confirm(`Delete "${c.name}"?`)) deleteMut.mutate(c.id);
                        }}
                      >
                        Delete
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

function EmptyState() {
  return (
    <Card>
      <CardContent className="flex flex-col items-center justify-center py-16 text-center space-y-3">
        <div className="flex h-12 w-12 items-center justify-center rounded-full bg-muted">
          <Database className="h-6 w-6 text-muted-foreground" />
        </div>
        <div>
          <h3 className="text-base font-semibold">No connections yet</h3>
          <p className="text-sm text-muted-foreground mt-1 max-w-sm">
            Add your source database (e.g. a Supabase project) and your destination (vanilla Postgres) to get started.
          </p>
        </div>
        <Button asChild>
          <Link href="/connections/new">
            <Plus className="h-4 w-4" /> New connection
          </Link>
        </Button>
      </CardContent>
    </Card>
  );
}
