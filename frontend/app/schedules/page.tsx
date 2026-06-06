"use client";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { CalendarClock, Pause, Play, Plus, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import type { Schedule } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { PageHeader } from "@/components/page-header";

export default function SchedulesPage() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ["schedules"], queryFn: api.listSchedules });

  const toggleMut = useMutation({
    mutationFn: (s: Schedule) => api.updateSchedule(s.id, { enabled: !s.enabled }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["schedules"] }),
    onError: (e) => toast.error(String(e)),
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => api.deleteSchedule(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["schedules"] });
      toast.success("Deleted");
    },
    onError: (e) => toast.error(String(e)),
  });

  return (
    <div>
      <PageHeader
        title="Schedules"
        description="Run saved SQL scripts against one or many connections on a cron schedule — e.g. nightly row-count checks. Each run is recorded so you can review what happened."
        actions={
          <Button asChild>
            <Link href="/schedules/new">
              <Plus className="h-4 w-4 mr-1.5" /> New schedule
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
              <CalendarClock className="h-6 w-6 text-muted-foreground" />
            </div>
            <div>
              <h3 className="text-base font-semibold">No schedules yet</h3>
              <p className="text-sm text-muted-foreground mt-1 max-w-sm">
                Schedule a saved SQL script to run automatically against your connections.
              </p>
            </div>
            <Button asChild variant="outline">
              <Link href="/schedules/new">New schedule</Link>
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
                  <TableHead>Target</TableHead>
                  <TableHead className="font-mono">Cron</TableHead>
                  <TableHead>Timezone</TableHead>
                  <TableHead>Next run</TableHead>
                  <TableHead>Last run</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="w-0" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.map((s) => (
                  <TableRow key={s.id}>
                    <TableCell className="font-medium">
                      <Link href={`/schedules/${s.id}`} className="hover:underline">
                        {s.name}
                      </Link>
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      <span className="inline-flex items-center gap-2">
                        <Badge variant="outline" className="font-normal">
                          {s.target_kind === "tap" ? "Tap" : "SQL"}
                        </Badge>
                        <span className="truncate">
                          {s.target_kind === "tap"
                            ? s.tap_name ?? "—"
                            : s.script_name ?? "—"}
                          {s.target_kind === "tap" && s.tap_write_mode === "replace" && (
                            <span className="ml-1 text-xs text-destructive">(truncate)</span>
                          )}
                        </span>
                      </span>
                    </TableCell>
                    <TableCell className="font-mono text-xs">{s.cron}</TableCell>
                    <TableCell className="text-muted-foreground text-xs">{s.timezone}</TableCell>
                    <TableCell className="text-muted-foreground whitespace-nowrap">
                      {s.enabled && s.next_run_at ? new Date(s.next_run_at).toLocaleString() : "—"}
                    </TableCell>
                    <TableCell className="text-muted-foreground whitespace-nowrap">
                      {s.last_run_at ? new Date(s.last_run_at).toLocaleString() : "—"}
                    </TableCell>
                    <TableCell>
                      <Badge variant={s.enabled ? "success" : "secondary"}>
                        {s.enabled ? "enabled" : "paused"}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right whitespace-nowrap">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => toggleMut.mutate(s)}
                        disabled={toggleMut.isPending}
                        title={s.enabled ? "Pause this schedule" : "Resume this schedule"}
                      >
                        {s.enabled ? (
                          <>
                            <Pause className="h-4 w-4 mr-1.5" /> Pause
                          </>
                        ) : (
                          <>
                            <Play className="h-4 w-4 mr-1.5" /> Resume
                          </>
                        )}
                      </Button>
                      <Button asChild variant="ghost" size="sm">
                        <Link href={`/schedules/${s.id}`}>Open</Link>
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
