"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  ArrowRightLeft,
  CalendarClock,
  Database,
  GitCompareArrows,
  Network,
  Plus,
  Radio,
  ShieldCheck,
  Workflow,
  X,
} from "lucide-react";
import { api } from "@/lib/api";
import type { ActivityEntry, ActivityType, MetricsSeriesPoint } from "@/lib/types";
import { cn } from "@/lib/utils";
import { envStyle } from "@/lib/environments";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/page-header";
import { ActivityChart, SERIES_TYPES } from "@/components/activity-chart";
import { Sparkline } from "@/components/sparkline";

const RANGES = [7, 14, 30];

const STATUS_META: { key: string; label: string; color: string }[] = [
  { key: "succeeded", label: "Succeeded", color: "#10b981" },
  { key: "running", label: "Running", color: "#0ea5e9" },
  { key: "partial", label: "Partial", color: "#f59e0b" },
  { key: "failed", label: "Failed", color: "#ef4444" },
  { key: "cancelled", label: "Cancelled", color: "#94a3b8" },
  { key: "other", label: "Other", color: "#94a3b8" },
];

const TYPE_ICON: Record<ActivityType, React.ComponentType<{ className?: string }>> = {
  introspection: Database,
  comparison: GitCompareArrows,
  migration: ArrowRightLeft,
  verification: ShieldCheck,
  pipeline: Network,
  scheduled: CalendarClock,
  api_fetch: Radio,
};

function statusVariant(status: string): "success" | "destructive" | "secondary" | "outline" {
  const s = status.toLowerCase();
  if (s === "succeeded" || s === "passed") return "success";
  if (s === "failed") return "destructive";
  if (s === "running" || s === "pending" || s === "queued" || s === "in_progress") return "secondary";
  return "outline";
}

function ago(iso?: string | null): string {
  if (!iso) return "";
  const s = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

export default function DashboardPage() {
  const [days, setDays] = useState(14);
  const [typeFilter, setTypeFilter] = useState<ActivityType | null>(null);
  const [failuresOnly, setFailuresOnly] = useState(false);

  const metrics = useQuery({
    queryKey: ["metrics", days],
    queryFn: () => api.getMetrics(days),
    refetchInterval: 15_000,
  });
  const activity = useQuery({
    queryKey: ["activity"],
    queryFn: api.listActivity,
    refetchInterval: 5_000,
  });

  const t = metrics.data?.totals;
  const breakdown = metrics.data?.status_breakdown ?? {};
  const windowRuns = Object.values(breakdown).reduce((a, b) => a + b, 0);

  const series = metrics.data?.series ?? [];
  const sparkOf = (key: keyof Omit<MetricsSeriesPoint, "date">): number[] =>
    series.map((p) => p[key] || 0);

  const toggleType = (key: string) =>
    setTypeFilter((cur) => (cur === key ? null : (key as ActivityType)));

  const filteredActivity = (activity.data ?? []).filter(
    (e) =>
      (!typeFilter || e.type === typeFilter) &&
      (!failuresOnly || e.status.toLowerCase() === "failed"),
  );

  return (
    <div className="space-y-6">
      <PageHeader
        title="Dashboard"
        description="Activity across the app — connections, schemas, pipelines, schedules, and runs."
        actions={
          <>
            <Button asChild variant="outline">
              <Link href="/connections/new">
                <Plus className="h-4 w-4" /> New connection
              </Link>
            </Button>
            <Button asChild>
              <Link href="/pipelines/new">
                New pipeline <ArrowRight className="h-4 w-4" />
              </Link>
            </Button>
          </>
        }
      />

      {/* Stat cards */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        <StatCard
          title="Connections"
          value={t?.connections}
          icon={Database}
          href="/connections"
          spark={sparkOf("introspection")}
          sparkColor="#3b82f6"
        >
          <EnvDots byEnv={t?.connections_by_env} />
        </StatCard>
        <StatCard
          title="Migrations"
          value={t?.migration_runs}
          icon={ArrowRightLeft}
          href="/migrations"
          subtitle="runs"
          spark={sparkOf("migration")}
          sparkColor="#10b981"
        />
        <StatCard
          title="Pipelines"
          value={t?.pipelines}
          icon={Network}
          href="/pipelines"
          subtitle="ETL jobs"
          spark={sparkOf("pipeline")}
          sparkColor="#06b6d4"
        />
        <StatCard
          title="Taps"
          value={t?.taps}
          icon={Radio}
          href="/taps"
          subtitle={`${t?.tap_runs ?? 0} fetches`}
          spark={sparkOf("api_fetch")}
          sparkColor="#f97316"
        />
        <StatCard
          title="Schedules"
          value={t?.schedules}
          icon={CalendarClock}
          href="/schedules"
          subtitle="cron"
          spark={sparkOf("scheduled")}
          sparkColor="#ec4899"
        />
      </div>

      {/* Chart + status */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader className="flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-base">Activity</CardTitle>
            <div className="flex gap-1">
              {RANGES.map((r) => (
                <Button
                  key={r}
                  size="sm"
                  variant={r === days ? "secondary" : "ghost"}
                  className="h-7 px-2 text-xs"
                  onClick={() => setDays(r)}
                >
                  {r}d
                </Button>
              ))}
            </div>
          </CardHeader>
          <CardContent>
            {metrics.data ? (
              <ActivityChart series={metrics.data.series} activeKey={typeFilter} onSelect={toggleType} />
            ) : (
              <div className="h-[180px] animate-pulse rounded-md bg-muted" />
            )}
            <div className="mt-4 flex flex-wrap gap-x-1 gap-y-1.5">
              {SERIES_TYPES.map((s) => {
                const active = typeFilter === s.key;
                const dim = typeFilter && !active;
                return (
                  <button
                    key={s.key}
                    type="button"
                    onClick={() => toggleType(s.key)}
                    title="Click to filter the activity feed"
                    className={cn(
                      "flex items-center gap-1.5 rounded-md px-1.5 py-0.5 text-xs text-muted-foreground transition-colors hover:bg-accent",
                      active && "bg-accent text-foreground",
                      dim && "opacity-40",
                    )}
                  >
                    <span className="h-2.5 w-2.5 rounded-sm" style={{ backgroundColor: s.color }} />
                    {s.label}
                  </button>
                );
              })}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Run outcomes</CardTitle>
            <p className="text-xs text-muted-foreground">
              {windowRuns} run{windowRuns === 1 ? "" : "s"} in the last {days} days
            </p>
          </CardHeader>
          <CardContent>
            {windowRuns === 0 ? (
              <p className="py-6 text-center text-sm text-muted-foreground">No runs yet.</p>
            ) : (
              <>
                <div className="flex h-2.5 overflow-hidden rounded-full">
                  {STATUS_META.map((s) =>
                    breakdown[s.key] ? (
                      <div
                        key={s.key}
                        style={{ width: `${(breakdown[s.key] / windowRuns) * 100}%`, backgroundColor: s.color }}
                        title={`${s.label}: ${breakdown[s.key]}`}
                      />
                    ) : null,
                  )}
                </div>
                <ul className="mt-3 space-y-1.5">
                  {STATUS_META.filter((s) => breakdown[s.key]).map((s) => (
                    <li key={s.key} className="flex items-center justify-between text-sm">
                      <span className="flex items-center gap-2">
                        <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: s.color }} />
                        {s.label}
                      </span>
                      <span className="tabular-nums text-muted-foreground">{breakdown[s.key]}</span>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Recent activity */}
      <Card>
        <CardHeader className="flex-row items-center justify-between gap-2 space-y-0 pb-2">
          <div className="flex items-center gap-2">
            <CardTitle className="text-base">Recent activity</CardTitle>
            {typeFilter && (
              <button
                type="button"
                onClick={() => setTypeFilter(null)}
                className="inline-flex items-center gap-1 rounded-full bg-accent px-2 py-0.5 text-xs text-foreground hover:bg-accent/70"
                title="Clear type filter"
              >
                {typeFilter}
                <X className="h-3 w-3" />
              </button>
            )}
          </div>
          <div className="flex items-center gap-1">
            <Button
              variant={failuresOnly ? "destructive" : "ghost"}
              size="sm"
              className="text-xs"
              onClick={() => setFailuresOnly((v) => !v)}
            >
              Failures only
            </Button>
            <Button asChild variant="ghost" size="sm" className="text-xs">
              <Link href="/runs">
                All runs <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {!activity.data ? (
            <p className="text-sm text-muted-foreground">Loading…</p>
          ) : filteredActivity.length === 0 ? (
            <div className="flex flex-col items-center gap-2 py-10 text-center">
              <Workflow className="h-6 w-6 text-muted-foreground" />
              <p className="text-sm text-muted-foreground">
                {typeFilter || failuresOnly
                  ? "Nothing matches this filter."
                  : "No activity yet. Introspect a connection or run a pipeline."}
              </p>
            </div>
          ) : (
            <ul className="divide-y">
              {filteredActivity.slice(0, 12).map((e) => (
                <ActivityRow key={`${e.type}:${e.id}`} entry={e} />
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function StatCard({
  title,
  value,
  subtitle,
  icon: Icon,
  href,
  spark,
  sparkColor,
  children,
}: {
  title: string;
  value: number | undefined;
  subtitle?: string;
  icon: React.ComponentType<{ className?: string }>;
  href: string;
  spark?: number[];
  sparkColor?: string;
  children?: React.ReactNode;
}) {
  return (
    <Link href={href}>
      <Card className="hover:border-foreground/20 transition-colors">
        <CardHeader className="flex-row items-center justify-between pb-2">
          <CardTitle className="text-sm font-medium text-muted-foreground">{title}</CardTitle>
          <Icon className="h-4 w-4 text-muted-foreground" />
        </CardHeader>
        <CardContent>
          <div className="flex items-end justify-between gap-2">
            <div>
              <span className="text-3xl font-semibold tabular-nums">{value ?? "—"}</span>
              {subtitle && <span className="ml-2 text-xs text-muted-foreground">{subtitle}</span>}
            </div>
            {spark && spark.length > 0 && <Sparkline data={spark} color={sparkColor} />}
          </div>
          {children}
        </CardContent>
      </Card>
    </Link>
  );
}

function EnvDots({ byEnv }: { byEnv?: Record<string, number> }) {
  if (!byEnv) return null;
  const entries = (["production", "staging", "development"] as const)
    .map((e) => ({ env: e, n: byEnv[e] || 0 }))
    .filter((x) => x.n > 0);
  if (entries.length === 0) return null;
  return (
    <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1">
      {entries.map(({ env, n }) => {
        const st = envStyle(env);
        return (
          <span key={env} className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <span className={cn("h-2 w-2 rounded-full", st?.dot)} />
            {n} {st?.label.toLowerCase()}
          </span>
        );
      })}
    </div>
  );
}

function ActivityRow({ entry }: { entry: ActivityEntry }) {
  const Icon = TYPE_ICON[entry.type] ?? Workflow;
  const when = entry.finished_at || entry.started_at;
  return (
    <li>
      <Link href={entry.href} className="-mx-2 flex items-center gap-3 rounded px-2 py-2 hover:bg-accent/30">
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground">
          <Icon className="h-3.5 w-3.5" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium">{entry.label}</div>
          {entry.detail && <div className="truncate text-xs text-muted-foreground">{entry.detail}</div>}
        </div>
        <Badge variant={statusVariant(entry.status)} className="shrink-0">
          {entry.status}
        </Badge>
        <span className="w-16 shrink-0 text-right text-xs tabular-nums text-muted-foreground">{ago(when)}</span>
      </Link>
    </li>
  );
}
