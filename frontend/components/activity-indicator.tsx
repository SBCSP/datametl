"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

const ACTIVE_STATUSES = new Set(["pending", "queued", "running", "in_progress"]);

/** Lives in the sidebar footer. Polls the unified activity feed every 3s and surfaces a
 * compact "N running" pill when any background job is in flight. Click → /runs. Nothing
 * shows when the worker is idle. */
export function ActivityIndicator() {
  const { data } = useQuery({
    queryKey: ["activity"],
    queryFn: api.listActivity,
    refetchInterval: 3_000,
    // Don't refetch on focus — the 3s interval is enough and avoids burst-fetching when
    // the user tabs back to a long-idle browser tab.
    refetchOnWindowFocus: false,
    retry: false,
  });

  const active = (data ?? []).filter((e) => ACTIVE_STATUSES.has(e.status));
  if (active.length === 0) return null;

  // Group by type for the tooltip text — "1 introspection, 2 migrations" reads better
  // than just a number.
  const byType: Record<string, number> = {};
  for (const e of active) byType[e.type] = (byType[e.type] ?? 0) + 1;
  const summary = Object.entries(byType)
    .map(([t, n]) => `${n} ${t}${n === 1 ? "" : "s"}`)
    .join(", ");

  return (
    <Link
      href="/runs"
      className={cn(
        "flex items-center gap-1.5 px-1.5 py-1 rounded-md text-xs",
        "bg-amber-500/10 text-amber-700 dark:text-amber-400",
        "hover:bg-amber-500/20 transition-colors",
      )}
      title={`Worker is busy: ${summary}. Click to open the activity log.`}
    >
      <Loader2 className="h-3 w-3 animate-spin" />
      <span className="font-medium">{active.length} running</span>
    </Link>
  );
}
