"use client";

import { use } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { TapEditor } from "@/components/tap-editor";

export default function TapPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data, isLoading, isError } = useQuery({
    queryKey: ["tap", id],
    queryFn: () => api.getTap(id),
  });

  if (isLoading) return <p className="text-sm text-muted-foreground">Loading…</p>;
  if (isError || !data) return <p className="text-sm text-destructive">Tap not found.</p>;

  return <TapEditor key={data.id} tap={data} />;
}
