"use client";

import { useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  ArrowDown,
  ArrowUp,
  ArrowRightLeft,
  CheckCircle2,
  Database,
  Loader2,
  MinusCircle,
  Play,
  Plus,
  Save,
  Trash2,
  XCircle,
} from "lucide-react";
import { api } from "@/lib/api";
import type { Pipeline, PipelineRunStep, PipelineStepType, StepConfig } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { PageHeader } from "@/components/page-header";

const INLINE = "__inline__";

interface EditStep {
  key: string;
  name: string;
  step_type: PipelineStepType;
  config: StepConfig;
}

let keyCounter = 0;
const nextKey = () => `s${keyCounter++}`;

function toEditStep(s: { name: string; step_type: PipelineStepType; config: StepConfig }): EditStep {
  return { key: nextKey(), name: s.name, step_type: s.step_type, config: { ...s.config } };
}

export function PipelineEditor({ pipeline }: { pipeline?: Pipeline }) {
  const router = useRouter();
  const qc = useQueryClient();

  const [id, setId] = useState<string | null>(pipeline?.id ?? null);
  const [name, setName] = useState(pipeline?.name ?? "");
  const [description, setDescription] = useState(pipeline?.description ?? "");
  const [steps, setSteps] = useState<EditStep[]>(() =>
    (pipeline?.steps ?? []).map(toEditStep),
  );
  const [runId, setRunId] = useState<string | null>(null);

  const connections = useQuery({ queryKey: ["connections"], queryFn: api.listConnections });
  const scripts = useQuery({ queryKey: ["scripts"], queryFn: api.listScripts });

  const run = useQuery({
    queryKey: ["pipeline-run", runId],
    queryFn: () => api.getPipelineRun(runId!),
    enabled: !!runId,
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      return s === "succeeded" || s === "failed" ? false : 1200;
    },
  });

  const setStep = (i: number, patch: Partial<EditStep>) =>
    setSteps((prev) => prev.map((s, j) => (j === i ? { ...s, ...patch } : s)));
  const setConfig = (i: number, patch: StepConfig) =>
    setSteps((prev) => prev.map((s, j) => (j === i ? { ...s, config: { ...s.config, ...patch } } : s)));
  const removeStep = (i: number) => setSteps((prev) => prev.filter((_, j) => j !== i));
  const moveStep = (i: number, dir: -1 | 1) =>
    setSteps((prev) => {
      const j = i + dir;
      if (j < 0 || j >= prev.length) return prev;
      const copy = [...prev];
      [copy[i], copy[j]] = [copy[j], copy[i]];
      return copy;
    });
  const addStep = (step_type: PipelineStepType) =>
    setSteps((prev) => [
      ...prev,
      {
        key: nextKey(),
        name: "",
        step_type,
        config: step_type === "sql" ? { allow_writes: false } : { mode: "truncate" },
      },
    ]);

  const payloadSteps = useMemo(
    () => steps.map((s) => ({ name: s.name, step_type: s.step_type, config: s.config })),
    [steps],
  );

  const persist = async (): Promise<string> => {
    if (!name.trim()) throw new Error("Give the pipeline a name first");
    if (steps.length === 0) throw new Error("Add at least one step");
    const body = { name, description, steps: payloadSteps };
    const saved = id ? await api.updatePipeline(id, body) : await api.createPipeline(body);
    if (!id) {
      setId(saved.id);
      window.history.replaceState(null, "", `/pipelines/${saved.id}`);
    }
    qc.setQueryData(["pipeline", saved.id], saved);
    return saved.id;
  };

  const saveMut = useMutation({
    mutationFn: persist,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pipelines"] });
      toast.success("Saved");
    },
    onError: (e) => toast.error(String(e)),
  });

  const runMut = useMutation({
    mutationFn: async () => {
      const pid = await persist();
      return api.runPipeline(pid);
    },
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["pipelines"] });
      setRunId(r.run_id);
      toast.success("Pipeline run started");
    },
    onError: (e) => toast.error(String(e)),
  });

  const deleteMut = useMutation({
    mutationFn: () => api.deletePipeline(id!),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pipelines"] });
      toast.success("Deleted");
      router.push("/pipelines");
    },
    onError: (e) => toast.error(String(e)),
  });

  const running = runMut.isPending || (!!runId && run.data?.status !== "succeeded" && run.data?.status !== "failed");
  const canSave = !!name.trim() && steps.length > 0;

  return (
    <div>
      <PageHeader
        title={id ? "Edit pipeline" : "New pipeline"}
        description="Steps run top-to-bottom; if one fails the rest are skipped. Sources are read-only; transfers stream a source query into a destination table."
        breadcrumbs={[{ label: "Pipelines", href: "/pipelines" }, { label: id ? name || "Pipeline" : "New" }]}
        actions={
          <div className="flex gap-2">
            {id && (
              <Button variant="outline" onClick={() => deleteMut.mutate()} disabled={deleteMut.isPending}>
                <Trash2 className="h-4 w-4 mr-1.5" /> Delete
              </Button>
            )}
            <Button variant="outline" onClick={() => saveMut.mutate()} disabled={!canSave || saveMut.isPending}>
              <Save className="h-4 w-4 mr-1.5" /> Save
            </Button>
            <Button onClick={() => runMut.mutate()} disabled={!canSave || running}>
              {running ? <Loader2 className="h-4 w-4 mr-1.5 animate-spin" /> : <Play className="h-4 w-4 mr-1.5" />}
              Run
            </Button>
          </div>
        }
      />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_22rem]">
        {/* Builder */}
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-[1fr_2fr]">
            <div className="space-y-1.5">
              <Label htmlFor="pl-name">Name</Label>
              <Input id="pl-name" placeholder="e.g. Nightly orders sync" value={name} onChange={(e) => setName(e.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="pl-desc">Description</Label>
              <Input id="pl-desc" placeholder="Optional" value={description} onChange={(e) => setDescription(e.target.value)} />
            </div>
          </div>

          {steps.length === 0 && (
            <Card>
              <CardContent className="py-10 text-center text-sm text-muted-foreground">
                No steps yet. Add a SQL or Transfer step to get started.
              </CardContent>
            </Card>
          )}

          {steps.map((step, i) => (
            <StepCard
              key={step.key}
              index={i}
              total={steps.length}
              step={step}
              connections={connections.data ?? []}
              scripts={scripts.data ?? []}
              onName={(v) => setStep(i, { name: v })}
              onConfig={(patch) => setConfig(i, patch)}
              onMove={(dir) => moveStep(i, dir)}
              onRemove={() => removeStep(i)}
            />
          ))}

          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={() => addStep("sql")}>
              <Plus className="h-4 w-4 mr-1.5" /> SQL step
            </Button>
            <Button variant="outline" size="sm" onClick={() => addStep("transfer")}>
              <Plus className="h-4 w-4 mr-1.5" /> Transfer step
            </Button>
          </div>
        </div>

        {/* Run panel */}
        <RunPanel run={run.data?.steps ?? []} status={run.data?.status} error={run.data?.error ?? null} active={!!runId} />
      </div>
    </div>
  );
}

function StepCard({
  index,
  total,
  step,
  connections,
  scripts,
  onName,
  onConfig,
  onMove,
  onRemove,
}: {
  index: number;
  total: number;
  step: EditStep;
  connections: { id: string; name: string }[];
  scripts: { id: string; name: string }[];
  onName: (v: string) => void;
  onConfig: (patch: StepConfig) => void;
  onMove: (dir: -1 | 1) => void;
  onRemove: () => void;
}) {
  const cfg = step.config;
  const str = (k: string) => String(cfg[k] ?? "");

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0 gap-2 pb-3">
        <CardTitle className="flex items-center gap-2 text-sm">
          <span className="flex h-6 w-6 items-center justify-center rounded-full bg-muted text-xs font-semibold">
            {index + 1}
          </span>
          {step.step_type === "sql" ? (
            <Badge variant="secondary" className="gap-1"><Database className="h-3 w-3" /> SQL</Badge>
          ) : (
            <Badge variant="secondary" className="gap-1"><ArrowRightLeft className="h-3 w-3" /> Transfer</Badge>
          )}
          <Input
            className="h-7 w-48 text-sm"
            placeholder="Step name (optional)"
            value={step.name}
            onChange={(e) => onName(e.target.value)}
          />
        </CardTitle>
        <div className="flex items-center gap-0.5">
          <Button variant="ghost" size="icon" className="h-7 w-7" disabled={index === 0} onClick={() => onMove(-1)}>
            <ArrowUp className="h-4 w-4" />
          </Button>
          <Button variant="ghost" size="icon" className="h-7 w-7" disabled={index === total - 1} onClick={() => onMove(1)}>
            <ArrowDown className="h-4 w-4" />
          </Button>
          <Button variant="ghost" size="icon" className="h-7 w-7" onClick={onRemove}>
            <Trash2 className="h-4 w-4 text-muted-foreground" />
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {step.step_type === "sql" ? (
          <>
            <ConnSelect label="Connection" value={str("connection_id")} options={connections} onChange={(v) => onConfig({ connection_id: v })} />
            <SqlSource
              scripts={scripts}
              scriptId={str("script_id")}
              inlineSql={str("inline_sql")}
              onChange={(patch) => onConfig(patch)}
              inlineKey="inline_sql"
              scriptKey="script_id"
            />
            <label className="flex items-start gap-2 rounded-md border border-dashed px-2 py-2 text-xs cursor-pointer">
              <input
                type="checkbox"
                className="mt-0.5 h-4 w-4 accent-destructive"
                checked={!!cfg.allow_writes}
                onChange={(e) => onConfig({ allow_writes: e.target.checked })}
              />
              <span>
                <span className="font-medium text-foreground">Allow writes (commits changes)</span>
                <span className="mt-0.5 block text-muted-foreground">Off = read-only (rolled back). On for UPDATE/DDL/upsert steps.</span>
              </span>
            </label>
          </>
        ) : (
          <>
            <div className="grid gap-3 sm:grid-cols-2">
              <ConnSelect label="Source connection" value={str("source_connection_id")} options={connections} onChange={(v) => onConfig({ source_connection_id: v })} />
              <ConnSelect label="Destination connection" value={str("dest_connection_id")} options={connections} onChange={(v) => onConfig({ dest_connection_id: v })} />
            </div>
            <SqlSource
              label="Source query (single SELECT)"
              scripts={scripts}
              scriptId={str("source_script_id")}
              inlineSql={str("source_sql")}
              onChange={(patch) => onConfig(patch)}
              inlineKey="source_sql"
              scriptKey="source_script_id"
            />
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label>Destination table</Label>
                <Input placeholder="public.staging_orders" value={str("dest_table")} onChange={(e) => onConfig({ dest_table: e.target.value })} />
              </div>
              <div className="space-y-1.5">
                <Label>Mode</Label>
                <Select value={str("mode") || "truncate"} onValueChange={(v) => onConfig({ mode: v })}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="truncate">Truncate &amp; load</SelectItem>
                    <SelectItem value="append">Append</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="space-y-1.5">
              <Label>Destination columns <span className="text-muted-foreground">(optional, comma-separated; order must match the SELECT)</span></Label>
              <Input
                placeholder="id, name, total"
                value={Array.isArray(cfg.dest_columns) ? (cfg.dest_columns as string[]).join(", ") : ""}
                onChange={(e) => {
                  const cols = e.target.value.split(",").map((c) => c.trim()).filter(Boolean);
                  onConfig({ dest_columns: cols.length ? cols : undefined });
                }}
              />
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

function ConnSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: { id: string; name: string }[];
  onChange: (v: string) => void;
}) {
  return (
    <div className="space-y-1.5">
      <Label>{label}</Label>
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger><SelectValue placeholder="Choose a connection" /></SelectTrigger>
        <SelectContent>
          {options.map((c) => (
            <SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

function SqlSource({
  label = "SQL",
  scripts,
  scriptId,
  inlineSql,
  onChange,
  inlineKey,
  scriptKey,
}: {
  label?: string;
  scripts: { id: string; name: string }[];
  scriptId: string;
  inlineSql: string;
  onChange: (patch: StepConfig) => void;
  inlineKey: string;
  scriptKey: string;
}) {
  const mode = scriptId ? scriptId : INLINE;
  return (
    <div className="space-y-1.5">
      <Label>{label}</Label>
      <Select
        value={mode}
        onValueChange={(v) => {
          if (v === INLINE) onChange({ [scriptKey]: undefined });
          else onChange({ [scriptKey]: v, [inlineKey]: undefined });
        }}
      >
        <SelectTrigger><SelectValue placeholder="Saved script or inline SQL" /></SelectTrigger>
        <SelectContent>
          <SelectItem value={INLINE}>Inline SQL</SelectItem>
          {scripts.map((s) => (
            <SelectItem key={s.id} value={s.id}>{s.name}</SelectItem>
          ))}
        </SelectContent>
      </Select>
      {!scriptId && (
        <Textarea
          className="min-h-[6rem] font-mono text-xs"
          placeholder="SELECT …"
          value={inlineSql}
          onChange={(e) => onChange({ [inlineKey]: e.target.value })}
          spellCheck={false}
        />
      )}
    </div>
  );
}

function RunPanel({
  run,
  status,
  error,
  active,
}: {
  run: PipelineRunStep[];
  status?: string;
  error: string | null;
  active: boolean;
}) {
  return (
    <Card className="h-fit lg:sticky lg:top-4">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center justify-between text-sm">
          Run
          {status && (
            <Badge variant={status === "succeeded" ? "success" : status === "failed" ? "destructive" : "secondary"}>
              {status}
            </Badge>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {!active ? (
          <p className="text-sm text-muted-foreground">Press <span className="font-medium text-foreground">Run</span> to execute the pipeline. Progress shows here.</p>
        ) : run.length === 0 ? (
          <p className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" /> Starting…</p>
        ) : (
          <ul className="space-y-2">
            {run.map((s) => (
              <li key={s.id} className="rounded-md border p-2 text-sm">
                <div className="flex items-center gap-2">
                  <StepIcon status={s.status} />
                  <span className="font-medium">{s.step_order + 1}. {s.name || s.step_type}</span>
                  <Badge variant="outline" className="ml-auto text-[10px]">{s.step_type}</Badge>
                </div>
                <StepSummary step={s} />
                {s.error && <p className="mt-1 font-mono text-xs text-destructive">{s.error}</p>}
              </li>
            ))}
          </ul>
        )}
        {error && <p className="font-mono text-xs text-destructive">{error}</p>}
      </CardContent>
    </Card>
  );
}

function StepIcon({ status }: { status: string }) {
  if (status === "succeeded") return <CheckCircle2 className="h-4 w-4 text-emerald-500" />;
  if (status === "failed") return <XCircle className="h-4 w-4 text-destructive" />;
  if (status === "skipped") return <MinusCircle className="h-4 w-4 text-muted-foreground" />;
  if (status === "running") return <Loader2 className="h-4 w-4 animate-spin text-sky-500" />;
  return <span className="h-2 w-2 rounded-full bg-muted-foreground/40" />;
}

function StepSummary({ step }: { step: PipelineRunStep }) {
  const s = step.summary || {};
  if (step.step_type === "transfer" && typeof s.rows_written === "number") {
    return <p className="mt-0.5 text-xs text-muted-foreground">{s.rows_written} row(s) → {String(s.dest_table ?? "")}</p>;
  }
  if (step.step_type === "sql" && typeof s.statement_count === "number") {
    return <p className="mt-0.5 text-xs text-muted-foreground">{String(s.statement_count)} statement(s){typeof s.rows === "number" ? ` · ${s.rows} row(s)` : ""}</p>;
  }
  return null;
}
