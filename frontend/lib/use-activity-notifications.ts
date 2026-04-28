"use client";

import { useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { api } from "./api";
import type { ActivityEntry } from "./types";

const ACTIVE = new Set(["pending", "queued", "running", "in_progress"]);
const TERMINAL = new Set(["succeeded", "passed", "failed", "cancelled"]);

const TYPE_LABEL: Record<ActivityEntry["type"], string> = {
  introspection: "Introspection",
  comparison: "Comparison",
  migration: "Migration",
  verification: "Verification",
};

/** Mounted at the AppShell level so toasts fire on any page. Polls activity every 3s,
 * tracks which jobs were active last poll, and emits a success / error toast when one
 * transitions to a terminal status. */
export function useActivityNotifications() {
  const { data } = useQuery({
    queryKey: ["activity"],
    queryFn: api.listActivity,
    refetchInterval: 3_000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  // Tracks the IDs we last saw as active. Diffing against the next poll tells us which
  // ones flipped to a terminal state, and we toast for exactly those.
  const lastActive = useRef<Map<string, ActivityEntry> | null>(null);

  useEffect(() => {
    if (!data) return;

    const currentById = new Map<string, ActivityEntry>();
    for (const e of data) currentById.set(`${e.type}:${e.id}`, e);

    // First poll after mount: seed the set without firing toasts. Otherwise every job
    // that already finished before the user opened the app would notify on page load.
    if (lastActive.current === null) {
      const seed = new Map<string, ActivityEntry>();
      for (const e of data) {
        if (ACTIVE.has(e.status)) seed.set(`${e.type}:${e.id}`, e);
      }
      lastActive.current = seed;
      return;
    }

    const newlyTerminal: ActivityEntry[] = [];
    for (const [key, prev] of lastActive.current) {
      const now = currentById.get(key);
      if (!now) continue;
      if (TERMINAL.has(now.status) && !TERMINAL.has(prev.status)) {
        newlyTerminal.push(now);
      }
    }

    for (const e of newlyTerminal) {
      const label = TYPE_LABEL[e.type];
      const isFail = e.status === "failed" || e.status === "cancelled";
      const fn = isFail ? toast.error : toast.success;
      fn(`${label} ${e.status}`, {
        description: e.label,
        action: { label: "Open", onClick: () => (window.location.href = e.href) },
      });
    }

    // Refresh the active set for next diff.
    const nextActive = new Map<string, ActivityEntry>();
    for (const e of data) {
      if (ACTIVE.has(e.status)) nextActive.set(`${e.type}:${e.id}`, e);
    }
    lastActive.current = nextActive;
  }, [data]);
}
