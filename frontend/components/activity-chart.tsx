"use client";

import type { MetricsSeriesPoint } from "@/lib/types";

export interface SeriesType {
  key: keyof Omit<MetricsSeriesPoint, "date">;
  label: string;
  color: string;
}

/** Shared event-type config — reused by the chart lines and the dashboard legend. */
export const SERIES_TYPES: SeriesType[] = [
  { key: "introspection", label: "Introspections", color: "#3b82f6" }, // blue
  { key: "comparison", label: "Comparisons", color: "#8b5cf6" }, // violet
  { key: "migration", label: "Migrations", color: "#10b981" }, // emerald
  { key: "verification", label: "Verifications", color: "#f59e0b" }, // amber
  { key: "pipeline", label: "Pipelines", color: "#06b6d4" }, // cyan
  { key: "scheduled", label: "Scheduled", color: "#ec4899" }, // pink
];

function dayTotal(p: MetricsSeriesPoint): number {
  return SERIES_TYPES.reduce((s, t) => s + (p[t.key] || 0), 0);
}

function fmtDate(iso: string): string {
  return new Date(iso + "T00:00:00").toLocaleDateString([], { month: "short", day: "numeric" });
}

/** Dependency-free multi-line time series — one sparkline per event type, on a shared scale.
 * When `activeKey` is set the other lines dim; clicking a line / hover column calls `onSelect`. */
export function ActivityChart({
  series,
  height = 180,
  activeKey = null,
  onSelect,
}: {
  series: MetricsSeriesPoint[];
  height?: number;
  activeKey?: string | null;
  onSelect?: (key: string) => void;
}) {
  const n = series.length;
  const max = Math.max(1, ...series.flatMap((p) => SERIES_TYPES.map((t) => p[t.key] || 0)));
  const allZero = series.every((p) => dayTotal(p) === 0);

  if (allZero || n === 0) {
    return (
      <div className="flex items-center justify-center text-sm text-muted-foreground" style={{ height }}>
        No activity in this window yet.
      </div>
    );
  }

  const pad = 6;
  // X uses column centers so the lines line up with the hover columns below.
  const xAt = (i: number) => ((i + 0.5) / n) * 100;
  const yAt = (v: number) => height - pad - (v / max) * (height - pad * 2);
  const pathFor = (key: SeriesType["key"]) =>
    series.map((p, i) => `${i ? "L" : "M"}${xAt(i).toFixed(2)} ${yAt(p[key] || 0).toFixed(2)}`).join(" ");

  return (
    <div>
      <div className="relative" style={{ height }}>
        <svg
          width="100%"
          height={height}
          viewBox={`0 0 100 ${height}`}
          preserveAspectRatio="none"
          className="block"
        >
          {SERIES_TYPES.map((t) => {
            const active = activeKey === t.key;
            const dim = activeKey && !active;
            return (
              <path
                key={t.key}
                d={pathFor(t.key)}
                fill="none"
                stroke={t.color}
                strokeWidth={active ? 2.5 : 1.5}
                strokeOpacity={dim ? 0.2 : 1}
                strokeLinejoin="round"
                strokeLinecap="round"
                vectorEffect="non-scaling-stroke"
                onClick={onSelect ? () => onSelect(t.key) : undefined}
                className={onSelect ? "cursor-pointer" : undefined}
              />
            );
          })}
        </svg>

        {/* Transparent per-day columns for hover tooltips + a vertical guide. */}
        <div className="absolute inset-0 flex">
          {series.map((p) => {
            const total = dayTotal(p);
            const present = SERIES_TYPES.filter((t) => (p[t.key] || 0) > 0);
            return (
              <div key={p.date} className="group relative flex-1">
                <div className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-foreground/10 opacity-0 group-hover:opacity-100" />
                <div className="pointer-events-none absolute bottom-full left-1/2 z-10 mb-1 hidden -translate-x-1/2 whitespace-nowrap rounded-md border bg-popover px-2 py-1.5 text-xs shadow-md group-hover:block">
                  <div className="font-medium">{fmtDate(p.date)}</div>
                  <div className="mb-1 text-muted-foreground">{total} event{total === 1 ? "" : "s"}</div>
                  {present.map((t) => (
                    <div key={t.key} className="flex items-center gap-1.5">
                      <span className="h-2 w-2 rounded-sm" style={{ backgroundColor: t.color }} />
                      <span className="text-muted-foreground">{t.label}</span>
                      <span className="ml-auto tabular-nums">{p[t.key]}</span>
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div className="mt-1.5 flex justify-between text-[10px] text-muted-foreground">
        {series.length > 0 && <span>{fmtDate(series[0].date)}</span>}
        {series.length > 2 && <span>{fmtDate(series[Math.floor(series.length / 2)].date)}</span>}
        {series.length > 1 && <span>{fmtDate(series[series.length - 1].date)}</span>}
      </div>
    </div>
  );
}
