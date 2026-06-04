"use client";

import { use } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { PipelineEditor } from "@/components/pipeline-editor";

export default function PipelinePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data, isLoading, isError } = useQuery({
    queryKey: ["pipeline", id],
    queryFn: () => api.getPipeline(id),
  });

  if (isLoading) return <p className="text-sm text-muted-foreground">Loading…</p>;
  if (isError || !data) return <p className="text-sm text-destructive">Pipeline not found.</p>;

  return <PipelineEditor key={data.id} pipeline={data} />;
}
