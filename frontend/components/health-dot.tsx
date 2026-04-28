"use client";

import { useQuery } from "@tanstack/react-query";
import { cn } from "@/lib/utils";

const BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

async function ping(): Promise<boolean> {
  try {
    const res = await fetch(`${BASE}/health`, { cache: "no-store" });
    return res.ok;
  } catch {
    return false;
  }
}

export function HealthDot() {
  const { data, isLoading } = useQuery({
    queryKey: ["health"],
    queryFn: ping,
    refetchInterval: 10_000,
    retry: false,
  });

  const ok = !!data;
  const label = isLoading ? "checking…" : ok ? "API online" : "API offline";

  return (
    <div className="flex items-center gap-1.5 px-1 text-xs text-muted-foreground" title={label}>
      <span
        className={cn(
          "h-2 w-2 rounded-full",
          isLoading ? "bg-muted-foreground/40" : ok ? "bg-emerald-500" : "bg-destructive",
        )}
      />
      <span>API</span>
    </div>
  );
}
