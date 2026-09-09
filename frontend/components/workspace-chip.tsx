"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronsUpDown } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { TenantKind, TenantSummary } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

function kindLabel(kind: TenantKind): string {
  return kind === "organization" ? "Organization" : "Personal";
}

/** Active workspace chip for app chrome. Click reserved for a future switcher. */
export function WorkspaceChip({ className }: { className?: string }) {
  const { data: auth } = useQuery({
    queryKey: ["auth-status"],
    queryFn: api.authStatus,
    staleTime: 30_000,
    retry: false,
  });

  const canLoadWorkspace =
    !!auth?.auth_enabled && !!auth.authenticated;

  // Shares ["tenants-me"] with AppShell — TanStack Query dedupes the HTTP call.
  const { data } = useQuery({
    queryKey: ["tenants-me"],
    queryFn: api.tenantsMe,
    enabled: canLoadWorkspace,
    staleTime: 15_000,
    retry: false,
  });

  // Hidden on login / onboard modal / unauthenticated / auth-off.
  if (!canLoadWorkspace || !data || data.needs_onboarding || data.tenants.length === 0) {
    return null;
  }

  // Match backend order: first membership by created_at, id.
  const workspace: TenantSummary = data.tenants[0];

  return (
    <div className={cn("border-b px-3 py-2", className)}>
      <button
        type="button"
        title="Workspace switcher coming soon"
        aria-label={`Workspace: ${workspace.name}`}
        onClick={() => toast.message("Workspace switcher coming soon")}
        className={cn(
          "flex w-full items-center gap-2 rounded-md border bg-background/60 px-2.5 py-1.5 text-left transition-colors",
          "hover:bg-accent/50 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
        )}
      >
        <div className="min-w-0 flex-1">
          <div className="truncate text-xs font-medium leading-tight">{workspace.name}</div>
          <div className="mt-0.5 flex items-center gap-1.5">
            <span className="text-[10px] text-muted-foreground">Workspace</span>
            <Badge
              variant="secondary"
              className="h-4 px-1.5 text-[9px] font-normal text-muted-foreground"
            >
              {kindLabel(workspace.kind)}
            </Badge>
          </div>
        </div>
        <ChevronsUpDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground/70" aria-hidden />
      </button>
    </div>
  );
}
