"use client";

import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { CheckCircle2, Loader2, Play, XCircle } from "lucide-react";
import { api } from "@/lib/api";
import type { SchemaApplyResult } from "@/lib/types";
import { useJob } from "@/lib/use-job";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { envStyle } from "@/lib/environments";

export function ApplySchemaDialog({
  snapshotId,
  sourceConnectionId,
  open,
  onOpenChange,
}: {
  snapshotId: string;
  sourceConnectionId: string;
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const [target, setTarget] = useState("");
  const [override, setOverride] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);

  const connections = useQuery({ queryKey: ["connections"], queryFn: api.listConnections, enabled: open });
  const targets = (connections.data ?? []).filter((c) => c.id !== sourceConnectionId);

  const ddl = useQuery({
    queryKey: ["snapshot-ddl", snapshotId, override],
    queryFn: () => api.getSnapshotDdl(snapshotId, override || undefined),
    enabled: open,
  });

  const job = useJob(jobId);
  const applying = !!jobId && job.data?.status !== "complete";
  const result = job.data?.status === "complete" ? (job.data.result as SchemaApplyResult | null) : null;

  const applyMut = useMutation({
    mutationFn: () => api.applySchema(snapshotId, { connection_id: target, schema_override: override || null }),
    onSuccess: (r) => {
      setJobId(r.job_id);
      toast.success("Applying schema…");
    },
    onError: (e) => toast.error(String(e)),
  });

  const targetEnv = envStyle(targets.find((t) => t.id === target)?.environment);

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        onOpenChange(v);
        if (!v) setJobId(null);
      }}
    >
      <DialogContent className="max-w-2xl overflow-hidden">
        <DialogHeader className="min-w-0">
          <DialogTitle>Apply schema to a database</DialogTitle>
          <DialogDescription className="break-words">
            Creates this snapshot&apos;s structure — extensions, schemas, tables, indexes, and
            foreign keys — on the target. Tables use <code>IF NOT EXISTS</code>. Views, RLS
            policies, triggers, functions, and custom types are not included (lightweight mode).
          </DialogDescription>
        </DialogHeader>

        <div className="min-w-0 space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label>Target connection</Label>
              <Select value={target} onValueChange={setTarget}>
                <SelectTrigger>
                  <SelectValue placeholder="Choose a destination" />
                </SelectTrigger>
                <SelectContent>
                  {targets.map((c) => {
                    const st = envStyle(c.environment);
                    return (
                      <SelectItem key={c.id} value={c.id}>
                        <span className="flex items-center gap-2">
                          {st && <span className={`h-2.5 w-2.5 rounded-full ${st.dot}`} />}
                          {c.name}
                        </span>
                      </SelectItem>
                    );
                  })}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label>Target schema override <span className="text-muted-foreground">(optional)</span></Label>
              <Input
                placeholder="(keep source schemas)"
                value={override}
                onChange={(e) => setOverride(e.target.value)}
              />
            </div>
          </div>

          {targetEnv?.label === "Production" && (
            <p className="rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-700 dark:text-red-300">
              Heads up: the target is labelled <strong>Production</strong>. This will create objects there.
            </p>
          )}

          {/* DDL preview */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <Label>DDL preview</Label>
              <span className="text-xs text-muted-foreground">
                {ddl.data ? `${ddl.data.statement_count} statements` : ""}
              </span>
            </div>
            <pre className="max-h-56 overflow-auto rounded-md border bg-muted px-3 py-2 font-mono text-[11px] leading-relaxed">
              {ddl.isLoading ? "Loading…" : ddl.data?.sql || "(no DDL — snapshot has no tables)"}
            </pre>
          </div>

          {/* Results */}
          {result && (
            <div className="space-y-2 rounded-md border p-3">
              <div className="flex items-center gap-2 text-sm font-medium">
                {result.fail_count === 0 ? (
                  <CheckCircle2 className="h-4 w-4 text-emerald-500" />
                ) : (
                  <XCircle className="h-4 w-4 text-destructive" />
                )}
                Applied to {result.connection_name}: {result.ok_count}/{result.statement_count} succeeded
                {result.fail_count > 0 && ` · ${result.fail_count} failed`}
              </div>
              {result.statements.filter((s) => !s.ok).length > 0 && (
                <ul className="max-h-40 space-y-1.5 overflow-auto">
                  {result.statements
                    .filter((s) => !s.ok)
                    .map((s) => (
                      <li key={s.index} className="rounded bg-destructive/5 p-1.5 text-xs">
                        <div className="font-mono text-destructive">{s.error}</div>
                        <div className="mt-0.5 truncate font-mono text-muted-foreground">{s.sql}</div>
                      </li>
                    ))}
                </ul>
              )}
              {result.fail_count > 0 && (
                <p className="text-xs text-muted-foreground">
                  Failures are usually missing extensions or FKs to schemas you didn&apos;t include — each
                  statement ran independently, so successful objects were still created.
                </p>
              )}
            </div>
          )}

          <div className="flex items-center justify-end gap-2">
            <Button variant="ghost" onClick={() => onOpenChange(false)}>
              Close
            </Button>
            <Button
              variant="destructive"
              onClick={() => applyMut.mutate()}
              disabled={!target || applying || applyMut.isPending}
            >
              {applying ? <Loader2 className="h-4 w-4 mr-1.5 animate-spin" /> : <Play className="h-4 w-4 mr-1.5" />}
              {applying ? "Applying…" : "Apply schema"}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
