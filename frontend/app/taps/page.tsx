"use client";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { CalendarClock, Plus, Radio, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import type { TapSummary } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { PageHeader } from "@/components/page-header";

const RUN_VARIANT: Record<string, "success" | "destructive" | "secondary" | "outline"> = {
  succeeded: "success",
  failed: "destructive",
  running: "secondary",
};

export default function TapsPage() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ["taps"], queryFn: api.listTaps });

  const deleteMut = useMutation({
    mutationFn: (id: string) => api.deleteTap(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["taps"] });
      toast.success("Deleted");
    },
    onError: (e) => toast.error(String(e)),
  });

  return (
    <div>
      <PageHeader
        title="Taps"
        description="Connect to any REST/JSON API and land the response into your databases — manually or (soon) on a schedule. Pick a destination, or run without one to preview the shape."
        actions={
          <Button asChild>
            <Link href="/taps/new">
              <Plus className="h-4 w-4 mr-1.5" /> New tap
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
              <Radio className="h-6 w-6 text-muted-foreground" />
            </div>
            <div>
              <h3 className="text-base font-semibold">No taps yet</h3>
              <p className="text-sm text-muted-foreground mt-1 max-w-sm">
                Add an API endpoint and pull its JSON into your databases.
              </p>
            </div>
            <Button asChild variant="outline">
              <Link href="/taps/new">New tap</Link>
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
                  <TableHead>Endpoint</TableHead>
                  <TableHead className="text-right">Destinations</TableHead>
                  <TableHead>Schedule</TableHead>
                  <TableHead>Last fetch</TableHead>
                  <TableHead className="w-0" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.map((t) => (
                  <TableRow key={t.id}>
                    <TableCell className="font-medium">
                      <Link href={`/taps/${t.id}`} className="hover:underline">
                        {t.name}
                      </Link>
                    </TableCell>
                    <TableCell className="max-w-[28rem] truncate text-xs text-muted-foreground">
                      <span className="font-mono">{t.method}</span> {t.url}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{t.dest_count || "—"}</TableCell>
                    <TableCell className="whitespace-nowrap">
                      <TapScheduleIndicator tap={t} />
                    </TableCell>
                    <TableCell className="whitespace-nowrap">
                      {t.last_run_status ? (
                        <span className="inline-flex items-center gap-2">
                          <Badge variant={RUN_VARIANT[t.last_run_status] ?? "outline"}>
                            {t.last_run_status}
                          </Badge>
                          <span className="text-xs text-muted-foreground">
                            {t.last_run_at ? new Date(t.last_run_at).toLocaleString() : ""}
                          </span>
                        </span>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </TableCell>
                    <TableCell className="text-right whitespace-nowrap">
                      <Button asChild variant="ghost" size="sm">
                        <Link href={`/taps/${t.id}`}>Open</Link>
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => deleteMut.mutate(t.id)}
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

/** Shows whether a tap is on a schedule (and whether that schedule is active). Links to /schedules. */
function TapScheduleIndicator({ tap }: { tap: TapSummary }) {
  if (!tap.is_scheduled) {
    return <span className="text-muted-foreground">—</span>;
  }
  return (
    <Link
      href="/schedules"
      className="inline-flex items-center gap-1.5 text-xs hover:underline"
      title={tap.schedule_enabled ? "On an active schedule" : "Scheduled but paused"}
    >
      <CalendarClock
        className={`h-3.5 w-3.5 ${tap.schedule_enabled ? "text-foreground" : "text-muted-foreground"}`}
      />
      <span className={tap.schedule_enabled ? "" : "text-muted-foreground"}>
        {tap.schedule_enabled ? "Scheduled" : "Paused"}
      </span>
    </Link>
  );
}
