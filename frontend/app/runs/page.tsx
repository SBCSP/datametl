"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowRightLeft,
  Database,
  GitCompareArrows,
  History,
  Loader2,
  ShieldCheck,
} from "lucide-react";
import { api } from "@/lib/api";
import type { ActivityEntry, ActivityType } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { PageHeader } from "@/components/page-header";

const TYPE_META: Record<ActivityType, { icon: React.ComponentType<{ className?: string }>; label: string }> = {
  introspection: { icon: Database, label: "Introspect" },
  comparison: { icon: GitCompareArrows, label: "Compare" },
  migration: { icon: ArrowRightLeft, label: "Migrate" },
  verification: { icon: ShieldCheck, label: "Verify" },
};

const STATUS_VARIANT: Record<string, "secondary" | "warning" | "success" | "destructive" | "outline"> = {
  pending: "secondary",
  queued: "secondary",
  running: "warning",
  in_progress: "warning",
  succeeded: "success",
  passed: "success",
  failed: "destructive",
  cancelled: "outline",
  skipped: "outline",
  complete: "success",
};

const ALL: "all" = "all";
const TYPES: (ActivityType | typeof ALL)[] = [ALL, "introspection", "comparison", "migration", "verification"];

export default function RunsPage() {
  const { data, isLoading } = useQuery({
    queryKey: ["activity"],
    queryFn: api.listActivity,
    refetchInterval: 5_000,
  });

  const [typeFilter, setTypeFilter] = useState<ActivityType | typeof ALL>(ALL);
  const filtered = (data ?? []).filter((e) => typeFilter === ALL || e.type === typeFilter);

  return (
    <div>
      <PageHeader
        title="Runs"
        description="Unified activity log — every introspection, comparison, migration, and verification across the system."
      />

      <div className="mb-3 flex flex-wrap gap-2">
        {TYPES.map((t) => (
          <Button
            key={t}
            size="sm"
            variant={typeFilter === t ? "default" : "outline"}
            onClick={() => setTypeFilter(t)}
          >
            {t === ALL ? "All" : TYPE_META[t].label}
          </Button>
        ))}
      </div>

      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : filtered.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16 text-center space-y-3">
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-muted">
              <History className="h-6 w-6 text-muted-foreground" />
            </div>
            <p className="text-sm text-muted-foreground">No activity yet.</p>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Type</TableHead>
                  <TableHead>What</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Started</TableHead>
                  <TableHead>Duration</TableHead>
                  <TableHead></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filtered.map((e) => {
                  const Icon = TYPE_META[e.type].icon;
                  const dur = duration(e);
                  return (
                    <TableRow key={`${e.type}:${e.id}`}>
                      <TableCell>
                        <span className="inline-flex items-center gap-1.5 text-xs">
                          <Icon className="h-3.5 w-3.5 text-muted-foreground" />
                          <span>{TYPE_META[e.type].label}</span>
                        </span>
                      </TableCell>
                      <TableCell className="text-sm">
                        <span className="font-medium">{e.label}</span>
                        {e.detail && (
                          <span className="block text-xs text-muted-foreground truncate max-w-[44ch]">
                            {e.detail}
                          </span>
                        )}
                      </TableCell>
                      <TableCell>
                        <Badge variant={STATUS_VARIANT[e.status] ?? "outline"}>
                          {e.status === "running" || e.status === "in_progress" ? (
                            <>
                              <Loader2 className="h-3 w-3 mr-1 animate-spin" />
                              {e.status}
                            </>
                          ) : (
                            e.status
                          )}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {e.started_at ? new Date(e.started_at).toLocaleString() : "—"}
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">{dur ?? "—"}</TableCell>
                      <TableCell className="text-right">
                        <Button size="sm" variant="ghost" asChild>
                          <Link href={e.href}>Open →</Link>
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

function duration(e: ActivityEntry): string | null {
  if (!e.started_at || !e.finished_at) return null;
  const ms = new Date(e.finished_at).getTime() - new Date(e.started_at).getTime();
  if (ms < 0) return null;
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60_000).toFixed(1)}m`;
}
