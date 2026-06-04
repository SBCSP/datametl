"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { CalendarClock, Clock, History, Loader2, Pause, Play, Save, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import type { Schedule } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { PageHeader } from "@/components/page-header";
import { RunHistoryDialog } from "@/components/schedule-history";

// Intl.supportedValuesOf isn't in every TS lib target — access it defensively.
const _intl = Intl as unknown as { supportedValuesOf?: (k: string) => string[] };
const TIMEZONES: string[] = _intl.supportedValuesOf?.("timeZone") ?? ["UTC"];
const BROWSER_TZ =
  (typeof Intl !== "undefined" && Intl.DateTimeFormat().resolvedOptions().timeZone) || "UTC";

const PRESETS: { label: string; cron: string }[] = [
  { label: "Every 15 min", cron: "*/15 * * * *" },
  { label: "Hourly", cron: "0 * * * *" },
  { label: "Daily 2am", cron: "0 2 * * *" },
  { label: "Weekdays 6am", cron: "0 6 * * 1-5" },
  { label: "Weekly (Mon)", cron: "0 9 * * 1" },
];

export function ScheduleEditor({ schedule }: { schedule?: Schedule }) {
  const router = useRouter();
  const qc = useQueryClient();

  const [id, setId] = useState<string | null>(schedule?.id ?? null);
  const [name, setName] = useState(schedule?.name ?? "");
  const [scriptId, setScriptId] = useState(schedule?.script_id ?? "");
  const [cron, setCron] = useState(schedule?.cron ?? "0 2 * * *");
  const [tz, setTz] = useState(schedule?.timezone ?? BROWSER_TZ);
  const [allowWrites, setAllowWrites] = useState(schedule?.allow_writes ?? false);
  const [enabled, setEnabled] = useState(schedule?.enabled ?? true);
  const [selected, setSelected] = useState<Set<string>>(
    new Set(schedule?.connection_ids ?? []),
  );
  const [historyOpen, setHistoryOpen] = useState(false);

  const scripts = useQuery({ queryKey: ["scripts"], queryFn: api.listScripts });
  const connections = useQuery({ queryKey: ["connections"], queryFn: api.listConnections });

  // Live "next runs" preview — re-fetched as the cron / timezone change.
  const previewQ = useQuery({
    queryKey: ["cron-preview", cron, tz],
    queryFn: () => api.previewCron(cron, tz),
    enabled: cron.trim().length > 0,
    retry: false,
  });

  const toggle = (cid: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(cid)) next.delete(cid);
      else next.add(cid);
      return next;
    });

  const body = useMemo(
    () => ({
      name: name.trim() || null,
      script_id: scriptId,
      connection_ids: Array.from(selected),
      cron: cron.trim(),
      timezone: tz,
      allow_writes: allowWrites,
      enabled,
    }),
    [name, scriptId, selected, cron, tz, allowWrites, enabled],
  );

  const saveMut = useMutation({
    mutationFn: async () => {
      if (!scriptId) throw new Error("Pick a script to schedule");
      if (selected.size === 0) throw new Error("Select at least one connection");
      if (id) return api.updateSchedule(id, body);
      return api.createSchedule(body);
    },
    onSuccess: (s) => {
      qc.invalidateQueries({ queryKey: ["schedules"] });
      toast.success("Schedule saved");
      if (!id) {
        setId(s.id);
        window.history.replaceState(null, "", `/schedules/${s.id}`);
      }
    },
    onError: (e) => toast.error(String(e)),
  });

  const runNowMut = useMutation({
    mutationFn: async () => {
      if (!id) throw new Error("Save the schedule first");
      return api.runScheduleNow(id);
    },
    onSuccess: () => toast.success("Run queued — check History in a moment"),
    onError: (e) => toast.error(String(e)),
  });

  const deleteMut = useMutation({
    mutationFn: () => api.deleteSchedule(id!),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["schedules"] });
      toast.success("Deleted");
      router.push("/schedules");
    },
    onError: (e) => toast.error(String(e)),
  });

  // Pause/resume persists immediately (independent of the big Save) so it's a one-click action.
  const pauseMut = useMutation({
    mutationFn: async () => {
      if (!id) throw new Error("Save the schedule first");
      return api.updateSchedule(id, { enabled: !enabled });
    },
    onSuccess: (s) => {
      setEnabled(s.enabled);
      qc.invalidateQueries({ queryKey: ["schedules"] });
      qc.invalidateQueries({ queryKey: ["schedule", id] });
      toast.success(s.enabled ? "Schedule resumed" : "Schedule paused");
    },
    onError: (e) => toast.error(String(e)),
  });

  const canSave = !!scriptId && selected.size > 0 && cron.trim().length > 0 && !saveMut.isPending;

  return (
    <div>
      <PageHeader
        title={id ? "Edit schedule" : "New schedule"}
        description="Run a saved SQL script against one or more connections on a cron schedule. Times are interpreted in the schedule's timezone."
        breadcrumbs={[{ label: "Schedules", href: "/schedules" }, { label: id ? name || "Schedule" : "New" }]}
        actions={
          <div className="flex gap-2">
            {id && (
              <>
                <Button
                  variant="outline"
                  onClick={() => pauseMut.mutate()}
                  disabled={pauseMut.isPending}
                  title={enabled ? "Pause this schedule" : "Resume this schedule"}
                >
                  {pauseMut.isPending ? (
                    <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />
                  ) : enabled ? (
                    <Pause className="h-4 w-4 mr-1.5" />
                  ) : (
                    <Play className="h-4 w-4 mr-1.5" />
                  )}
                  {enabled ? "Pause" : "Resume"}
                </Button>
                <Button variant="outline" onClick={() => setHistoryOpen(true)}>
                  <History className="h-4 w-4 mr-1.5" /> History
                </Button>
                <Button
                  variant="outline"
                  onClick={() => runNowMut.mutate()}
                  disabled={runNowMut.isPending}
                >
                  {runNowMut.isPending ? (
                    <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />
                  ) : (
                    <Play className="h-4 w-4 mr-1.5" />
                  )}
                  Run now
                </Button>
                <Button variant="outline" onClick={() => deleteMut.mutate()} disabled={deleteMut.isPending}>
                  <Trash2 className="h-4 w-4 mr-1.5" /> Delete
                </Button>
              </>
            )}
            <Button onClick={() => saveMut.mutate()} disabled={!canSave}>
              <Save className="h-4 w-4 mr-1.5" /> Save
            </Button>
          </div>
        }
      />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_18rem]">
        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="sched-name">Name</Label>
            <Input
              id="sched-name"
              placeholder="Defaults to the script name"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>

          <div className="space-y-1.5">
            <Label>Script</Label>
            <Select value={scriptId} onValueChange={setScriptId}>
              <SelectTrigger>
                <SelectValue placeholder={scripts.isLoading ? "Loading…" : "Choose a script"} />
              </SelectTrigger>
              <SelectContent>
                {scripts.data?.map((s) => (
                  <SelectItem key={s.id} value={s.id}>
                    {s.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {scripts.data && scripts.data.length === 0 && (
              <p className="text-xs text-muted-foreground">
                No scripts yet — create one under SQL Scripts first.
              </p>
            )}
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="sched-cron">Cron expression</Label>
            <Input
              id="sched-cron"
              className="font-mono"
              placeholder="0 2 * * *"
              value={cron}
              onChange={(e) => setCron(e.target.value)}
              spellCheck={false}
            />
            <div className="flex flex-wrap gap-1.5 pt-1">
              {PRESETS.map((p) => (
                <button
                  key={p.cron}
                  type="button"
                  onClick={() => setCron(p.cron)}
                  className="rounded-full border px-2.5 py-0.5 text-xs text-muted-foreground hover:bg-accent hover:text-foreground"
                >
                  {p.label}
                </button>
              ))}
            </div>
            <p className="text-xs text-muted-foreground">
              Standard 5-field cron: minute hour day-of-month month day-of-week.
            </p>
          </div>

          <div className="space-y-1.5">
            <Label>Timezone</Label>
            <Select value={tz} onValueChange={setTz}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="max-h-72">
                {TIMEZONES.map((z) => (
                  <SelectItem key={z} value={z}>
                    {z}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Next-runs preview */}
          <Card className="bg-muted/40">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm flex items-center gap-2">
                <Clock className="h-4 w-4" /> Next runs
              </CardTitle>
            </CardHeader>
            <CardContent className="text-sm">
              {!cron.trim() ? (
                <p className="text-muted-foreground">Enter a cron expression.</p>
              ) : previewQ.isLoading ? (
                <p className="text-muted-foreground">Calculating…</p>
              ) : previewQ.data && !previewQ.data.valid ? (
                <p className="text-destructive">{previewQ.data.error ?? "Invalid cron expression"}</p>
              ) : previewQ.data?.next_runs.length ? (
                <ul className="space-y-1">
                  {previewQ.data.next_runs.map((iso) => (
                    <li key={iso} className="tabular-nums text-muted-foreground">
                      {new Date(iso).toLocaleString()}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-muted-foreground">—</p>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Connection picker + options */}
        <Card className="h-fit">
          <CardHeader>
            <CardTitle className="text-sm">Run against</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {connections.isLoading ? (
              <p className="text-sm text-muted-foreground">Loading…</p>
            ) : !connections.data?.length ? (
              <p className="text-sm text-muted-foreground">
                No connections yet. Add one under Connections first.
              </p>
            ) : (
              connections.data.map((c) => (
                <label
                  key={c.id}
                  className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-accent cursor-pointer"
                >
                  <input
                    type="checkbox"
                    className="h-4 w-4 accent-primary"
                    checked={selected.has(c.id)}
                    onChange={() => toggle(c.id)}
                  />
                  <span className="truncate">{c.name}</span>
                </label>
              ))
            )}

            <label className="mt-2 flex items-center gap-2 rounded-md px-2 py-1.5 text-sm cursor-pointer">
              <input
                type="checkbox"
                className="h-4 w-4 accent-primary"
                checked={enabled}
                onChange={(e) => setEnabled(e.target.checked)}
              />
              <span className="font-medium">Enabled</span>
            </label>

            <label className="flex items-start gap-2 rounded-md border border-dashed px-2 py-2 text-xs cursor-pointer">
              <input
                type="checkbox"
                className="mt-0.5 h-4 w-4 accent-destructive"
                checked={allowWrites}
                onChange={(e) => setAllowWrites(e.target.checked)}
              />
              <span>
                <span className="font-medium text-foreground">Allow writes (commits changes)</span>
                <span className="mt-0.5 block text-muted-foreground">
                  Off = read-only (rolled back). On = commits per connection; rolls back if any
                  statement fails.
                </span>
              </span>
            </label>
          </CardContent>
        </Card>
      </div>

      {id && (
        <RunHistoryDialog
          scheduleId={id}
          open={historyOpen}
          onOpenChange={setHistoryOpen}
          title={name || "Schedule"}
        />
      )}

      {!id && (
        <p className="mt-6 flex items-center gap-1.5 text-xs text-muted-foreground">
          <CalendarClock className="h-3.5 w-3.5" /> Save to activate — the worker checks for due
          schedules every minute.
        </p>
      )}
    </div>
  );
}
