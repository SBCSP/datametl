"use client";

import { use } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { ScriptEditor } from "@/components/script-editor";

export default function ScriptPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data, isLoading, isError } = useQuery({
    queryKey: ["script", id],
    queryFn: () => api.getScript(id),
  });

  if (isLoading) return <p className="text-sm text-muted-foreground">Loading…</p>;
  if (isError || !data) return <p className="text-sm text-destructive">Script not found.</p>;

  // Remount the editor when the loaded script changes, so its initial state is seeded correctly.
  return <ScriptEditor key={data.id} script={data} />;
}
