"use client";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { CalendarClock, FileCode, Plus, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import type { SqlScript } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { PageHeader } from "@/components/page-header";

export default function ScriptsPage() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ["scripts"], queryFn: api.listScripts });

  const deleteMut = useMutation({
    mutationFn: (id: string) => api.deleteScript(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["scripts"] });
      toast.success("Deleted");
    },
    onError: (e) => toast.error(String(e)),
  });

  return (
    <div>
      <PageHeader
        title="SQL Scripts"
        description="Save read-only SQL and run it against one or many connections at once — e.g. count rows across every database and compare side by side."
        actions={
          <Button asChild>
            <Link href="/scripts/new">
              <Plus className="h-4 w-4 mr-1.5" /> New script
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
              <FileCode className="h-6 w-6 text-muted-foreground" />
            </div>
            <div>
              <h3 className="text-base font-semibold">No scripts yet</h3>
              <p className="text-sm text-muted-foreground mt-1 max-w-sm">
                Create a script to run the same query across multiple connections at once.
              </p>
            </div>
            <Button asChild variant="outline">
              <Link href="/scripts/new">New script</Link>
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
                  <TableHead>Schedule</TableHead>
                  <TableHead className="text-right">Runs</TableHead>
                  <TableHead>Last run</TableHead>
                  <TableHead>Updated</TableHead>
                  <TableHead className="w-0" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.map((s) => (
                  <TableRow key={s.id}>
                    <TableCell className="font-medium">
                      <Link href={`/scripts/${s.id}`} className="hover:underline">
                        {s.name}
                      </Link>
                    </TableCell>
                    <TableCell>
                      <ScheduleIndicator script={s} />
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{s.run_count}</TableCell>
                    <TableCell className="text-muted-foreground whitespace-nowrap">
                      {s.last_run_at ? new Date(s.last_run_at).toLocaleString() : "—"}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {new Date(s.updated_at).toLocaleString()}
                    </TableCell>
                    <TableCell className="text-right whitespace-nowrap">
                      <Button asChild variant="ghost" size="sm">
                        <Link href={`/scripts/${s.id}`}>Open</Link>
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => deleteMut.mutate(s.id)}
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

/** Shows whether a script is on a schedule, plus the health of its most recent scheduled run.
 * Links to /schedules so the operator can manage it. */
function ScheduleIndicator({ script }: { script: SqlScript }) {
  if (!script.is_scheduled) {
    return <span className="text-muted-foreground">—</span>;
  }

  const status = script.last_scheduled_status;
  const health =
    status === "succeeded"
      ? { dot: "bg-emerald-500", label: "succeeding", text: "text-emerald-600 dark:text-emerald-400" }
      : status === "failed"
        ? { dot: "bg-destructive", label: "failing", text: "text-destructive" }
        : status === "partial"
          ? { dot: "bg-amber-500", label: "partial", text: "text-amber-600 dark:text-amber-500" }
          : status === "running"
            ? { dot: "bg-sky-500 animate-pulse", label: "running", text: "text-muted-foreground" }
            : { dot: "bg-muted-foreground/40", label: "no runs yet", text: "text-muted-foreground" };

  return (
    <Link
      href="/schedules"
      className="inline-flex items-center gap-1.5 text-xs hover:underline"
      title={`On a schedule · last run: ${health.label}`}
    >
      <CalendarClock
        className={`h-3.5 w-3.5 ${script.schedule_enabled ? "text-foreground" : "text-muted-foreground"}`}
      />
      <span className={script.schedule_enabled ? "" : "text-muted-foreground"}>
        {script.schedule_enabled ? "Scheduled" : "Paused"}
      </span>
      <span className={`h-2 w-2 rounded-full ${health.dot}`} aria-hidden />
      <span className={`${health.text}`}>{health.label}</span>
    </Link>
  );
}
