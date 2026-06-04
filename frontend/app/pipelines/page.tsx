"use client";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Network, Plus, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { PageHeader } from "@/components/page-header";

const RUN_VARIANT: Record<string, "success" | "destructive" | "secondary" | "outline"> = {
  succeeded: "success",
  failed: "destructive",
  running: "secondary",
  pending: "outline",
};

export default function PipelinesPage() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ["pipelines"], queryFn: api.listPipelines });

  const deleteMut = useMutation({
    mutationFn: (id: string) => api.deletePipeline(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pipelines"] });
      toast.success("Deleted");
    },
    onError: (e) => toast.error(String(e)),
  });

  return (
    <div>
      <PageHeader
        title="Pipelines"
        description="Build step-by-step ETL jobs — run SQL on a connection and stream query results between databases — then run them on demand or on a schedule."
        actions={
          <Button asChild>
            <Link href="/pipelines/new">
              <Plus className="h-4 w-4 mr-1.5" /> New pipeline
            </Link>
          </Button>
        }
      />

      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : !data?.length ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16 text-center space-y-3">
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-muted">
              <Network className="h-6 w-6 text-muted-foreground" />
            </div>
            <div>
              <h3 className="text-base font-semibold">No pipelines yet</h3>
              <p className="text-sm text-muted-foreground mt-1 max-w-sm">
                Chain SQL and data-transfer steps into a repeatable ETL job.
              </p>
            </div>
            <Button asChild variant="outline">
              <Link href="/pipelines/new">New pipeline</Link>
            </Button>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead className="text-right">Steps</TableHead>
                  <TableHead>Last run</TableHead>
                  <TableHead>Updated</TableHead>
                  <TableHead className="w-0" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.map((p) => (
                  <TableRow key={p.id}>
                    <TableCell className="font-medium">
                      <Link href={`/pipelines/${p.id}`} className="hover:underline">
                        {p.name}
                      </Link>
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{p.step_count}</TableCell>
                    <TableCell className="whitespace-nowrap">
                      {p.last_run_status ? (
                        <span className="inline-flex items-center gap-2">
                          <Badge variant={RUN_VARIANT[p.last_run_status] ?? "outline"}>
                            {p.last_run_status}
                          </Badge>
                          <span className="text-xs text-muted-foreground">
                            {p.last_run_at ? new Date(p.last_run_at).toLocaleString() : ""}
                          </span>
                        </span>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {new Date(p.updated_at).toLocaleString()}
                    </TableCell>
                    <TableCell className="text-right whitespace-nowrap">
                      <Button asChild variant="ghost" size="sm">
                        <Link href={`/pipelines/${p.id}`}>Open</Link>
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => deleteMut.mutate(p.id)}
                        disabled={deleteMut.isPending}
                      >
                        <Trash2 className="h-4 w-4 text-muted-foreground" />
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
