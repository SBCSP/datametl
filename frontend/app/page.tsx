"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  Database,
  GitCompareArrows,
  Plus,
  ShieldCheck,
} from "lucide-react";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/page-header";

export default function DashboardPage() {
  const connections = useQuery({ queryKey: ["connections"], queryFn: api.listConnections });
  const comparisons = useQuery({ queryKey: ["comparisons"], queryFn: api.listComparisons });

  const connectionCount = connections.data?.length ?? 0;
  const comparisonCount = comparisons.data?.length ?? 0;

  return (
    <div>
      <PageHeader
        title="Dashboard"
        description="Connect databases, snapshot schemas, compare and map types — all locally."
        actions={
          <>
            <Button asChild variant="outline">
              <Link href="/connections/new">
                <Plus className="h-4 w-4" /> New connection
              </Link>
            </Button>
            <Button asChild>
              <Link href="/comparisons/new">
                New comparison <ArrowRight className="h-4 w-4" />
              </Link>
            </Button>
          </>
        }
      />

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3 mb-8">
        <StatCard
          title="Connections"
          value={connectionCount}
          icon={Database}
          href="/connections"
          subtitle={connectionCount === 1 ? "database registered" : "databases registered"}
        />
        <StatCard
          title="Comparisons"
          value={comparisonCount}
          icon={GitCompareArrows}
          href="/comparisons"
          subtitle={comparisonCount === 1 ? "schema diff" : "schema diffs"}
        />
        <StatCard
          title="Migrations"
          value="—"
          icon={ShieldCheck}
          href="#"
          subtitle="Phase 2"
          disabled
        />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <RecentList
          title="Recent connections"
          empty="No connections yet."
          ctaLabel="Add a connection"
          ctaHref="/connections/new"
          items={(connections.data ?? []).slice(0, 5).map((c) => ({
            primary: c.name,
            secondary: new Date(c.created_at).toLocaleString(),
            href: `/schemas/${c.id}`,
            tag: c.engine,
          }))}
        />
        <RecentList
          title="Recent comparisons"
          empty="No comparisons yet."
          ctaLabel="Run a comparison"
          ctaHref="/comparisons/new"
          items={(comparisons.data ?? []).slice(0, 5).map((c) => ({
            primary: c.id.slice(0, 8) + "…",
            secondary: new Date(c.created_at).toLocaleString(),
            href: `/comparisons/${c.id}`,
          }))}
        />
      </div>
    </div>
  );
}

function StatCard({
  title,
  value,
  subtitle,
  icon: Icon,
  href,
  disabled,
}: {
  title: string;
  value: number | string;
  subtitle?: string;
  icon: React.ComponentType<{ className?: string }>;
  href: string;
  disabled?: boolean;
}) {
  const inner = (
    <Card className={disabled ? "opacity-60" : "hover:border-foreground/20 transition-colors"}>
      <CardHeader className="flex-row items-center justify-between pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">{title}</CardTitle>
        <Icon className="h-4 w-4 text-muted-foreground" />
      </CardHeader>
      <CardContent>
        <div className="flex items-baseline justify-between">
          <span className="text-3xl font-semibold tabular-nums">{value}</span>
          {subtitle && (
            <span className="text-xs text-muted-foreground">{subtitle}</span>
          )}
        </div>
      </CardContent>
    </Card>
  );
  if (disabled) return inner;
  return <Link href={href}>{inner}</Link>;
}

function RecentList({
  title,
  empty,
  ctaLabel,
  ctaHref,
  items,
}: {
  title: string;
  empty: string;
  ctaLabel: string;
  ctaHref: string;
  items: { primary: string; secondary: string; href: string; tag?: string }[];
}) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        {items.length === 0 ? (
          <div className="flex items-center justify-between py-2">
            <span className="text-sm text-muted-foreground">{empty}</span>
            <Button asChild size="sm" variant="outline">
              <Link href={ctaHref}>{ctaLabel}</Link>
            </Button>
          </div>
        ) : (
          <ul className="divide-y">
            {items.map((it, i) => (
              <li key={i}>
                <Link
                  href={it.href}
                  className="flex items-center justify-between py-2 hover:bg-accent/30 -mx-2 px-2 rounded"
                >
                  <div className="min-w-0">
                    <div className="text-sm font-medium truncate">{it.primary}</div>
                    <div className="text-xs text-muted-foreground">{it.secondary}</div>
                  </div>
                  {it.tag && <Badge variant="secondary">{it.tag}</Badge>}
                </Link>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
