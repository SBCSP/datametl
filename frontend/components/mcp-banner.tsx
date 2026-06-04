"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { X } from "lucide-react";
import { api } from "@/lib/api";

/** App-wide sticky banner shown whenever a connection is the active read-only MCP target. */
export function McpBanner() {
  const qc = useQueryClient();
  const { data } = useQuery({
    queryKey: ["mcp-active"],
    queryFn: api.getActiveMcp,
    refetchInterval: 5_000,
  });
  const deactivate = useMutation({
    mutationFn: () => api.mcpDeactivate(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["mcp-active"] });
      qc.invalidateQueries({ queryKey: ["connections"] });
      toast.success("MCP connection deactivated");
    },
    onError: (e) => toast.error(String(e)),
  });

  if (!data) return null;

  return (
    <div className="sticky top-0 z-30 flex items-center justify-between gap-3 border-b border-orange-500/40 bg-orange-500/15 px-4 py-2 text-sm text-orange-700 dark:text-orange-300 print:hidden">
      <div className="flex min-w-0 items-center gap-2">
        <span className="relative flex h-2.5 w-2.5 shrink-0">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-orange-500 opacity-60" />
          <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-orange-500" />
        </span>
        <span className="truncate font-medium">
          {data.name} — Active MCP Connection
          <span className="ml-1 font-normal opacity-70">({data.engine}, read-only)</span>
        </span>
      </div>
      <button
        type="button"
        onClick={() => deactivate.mutate()}
        disabled={deactivate.isPending}
        className="inline-flex shrink-0 items-center gap-1 rounded px-2 py-0.5 text-xs font-medium hover:bg-orange-500/20 disabled:opacity-60"
      >
        <X className="h-3.5 w-3.5" /> Deactivate
      </button>
    </div>
  );
}
