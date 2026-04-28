"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  ArrowRightLeft,
  Database,
  GitCompareArrows,
  History,
  LayoutDashboard,
  Settings,
  ShieldCheck,
  Workflow,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { ThemeToggle } from "@/components/theme-toggle";
import { HealthDot } from "@/components/health-dot";
import { ActivityIndicator } from "@/components/activity-indicator";

type NavItem = {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  phase2?: boolean;
  matchPrefix?: string;
};

const NAV: { section: string; items: NavItem[] }[] = [
  {
    section: "Workspace",
    items: [
      { href: "/", label: "Dashboard", icon: LayoutDashboard },
      { href: "/connections", label: "Connections", icon: Database, matchPrefix: "/connections" },
      { href: "/schemas", label: "Schemas", icon: Workflow, matchPrefix: "/schemas" },
      { href: "/comparisons", label: "Comparisons", icon: GitCompareArrows, matchPrefix: "/comparisons" },
      { href: "/mappings", label: "Mappings", icon: Workflow, matchPrefix: "/mappings" },
    ],
  },
  {
    section: "Migration",
    items: [
      { href: "/migrations", label: "Migrations", icon: ArrowRightLeft, matchPrefix: "/migrations" },
      { href: "/verification", label: "Verification", icon: ShieldCheck, matchPrefix: "/verification" },
      { href: "/runs", label: "Runs", icon: History, matchPrefix: "/runs" },
    ],
  },
  {
    section: "System",
    items: [{ href: "/settings", label: "Settings", icon: Settings, matchPrefix: "/settings" }],
  },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="hidden md:flex md:w-60 md:flex-col md:fixed md:inset-y-0 md:z-40 border-r bg-card">
      <div className="flex h-14 items-center gap-2 border-b px-4">
        <div className="flex h-8 w-8 items-center justify-center rounded-md bg-primary text-primary-foreground">
          <Activity className="h-4 w-4" />
        </div>
        <div className="flex flex-col leading-tight">
          <span className="text-sm font-semibold tracking-tight">DataMETL</span>
          <span className="text-[10px] text-muted-foreground">v0.1 · Phase 1</span>
        </div>
      </div>

      <nav className="flex-1 overflow-y-auto px-2 py-3 space-y-4">
        {NAV.map((group) => (
          <div key={group.section}>
            <div className="px-2 pb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              {group.section}
            </div>
            <ul className="space-y-0.5">
              {group.items.map((item) => (
                <li key={item.href}>
                  <NavLink item={item} pathname={pathname} />
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>

      <div className="border-t p-3 space-y-2">
        {/* Activity pill renders only when the worker is busy — gives users a global hint
            that something's running even if they navigated away from the originating page. */}
        <div className="flex items-center justify-center px-1 min-h-[1.5rem]">
          <ActivityIndicator />
        </div>
        <div className="flex items-center justify-between px-1">
          <HealthDot />
          <ThemeToggle />
        </div>
      </div>
    </aside>
  );
}

function NavLink({ item, pathname }: { item: NavItem; pathname: string }) {
  const active = item.matchPrefix
    ? pathname === item.matchPrefix || pathname.startsWith(item.matchPrefix + "/")
    : pathname === item.href;

  const Icon = item.icon;

  if (item.phase2) {
    return (
      <div
        className={cn(
          "flex items-center justify-between rounded-md px-2 py-1.5 text-sm",
          "text-muted-foreground/60 cursor-not-allowed",
        )}
        title="Available in Phase 2"
      >
        <span className="flex items-center gap-2">
          <Icon className="h-4 w-4" />
          {item.label}
        </span>
        <Badge variant="outline" className="text-[9px] px-1 py-0 h-4">
          Phase 2
        </Badge>
      </div>
    );
  }

  return (
    <Link
      href={item.href}
      className={cn(
        "flex items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors",
        active
          ? "bg-accent text-accent-foreground font-medium"
          : "text-muted-foreground hover:bg-accent/50 hover:text-foreground",
      )}
    >
      <Icon className="h-4 w-4" />
      {item.label}
    </Link>
  );
}
