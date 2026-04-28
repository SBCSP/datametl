"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "./api";

/** Poll a job until it completes. Use the returned `data.status` to drive UI. */
export function useJob(jobId: string | null | undefined) {
  return useQuery({
    queryKey: ["job", jobId],
    queryFn: () => api.jobStatus(jobId!),
    enabled: !!jobId,
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      return s === "complete" || s === "not_found" ? false : 1000;
    },
  });
}
