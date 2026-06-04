"use client";

import { use } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { ScheduleEditor } from "@/components/schedule-editor";

export default function SchedulePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data, isLoading, isError } = useQuery({
    queryKey: ["schedule", id],
    queryFn: () => api.getSchedule(id),
  });

  if (isLoading) return <p className="text-sm text-muted-foreground">Loading…</p>;
  if (isError || !data) return <p className="text-sm text-destructive">Schedule not found.</p>;

  return <ScheduleEditor key={data.id} schedule={data} />;
}
