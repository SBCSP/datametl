"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { CheckCircle2, FlaskConical, Loader2, Play, Plus, Save, Trash2, XCircle } from "lucide-react";
import { api } from "@/lib/api";
import type { Tap, TapRun, TapTestResult } from "@/lib/types";
import { useJob } from "@/lib/use-job";
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

const METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"] as const;

interface KV {
  key: string;
  value: string;
}
const toRows = (obj: Record<string, string> | undefined): KV[] =>
  Object.entries(obj ?? {}).map(([key, value]) => ({ key, value }));
const toObj = (rows: KV[]): Record<string, string> =>
  Object.fromEntries(rows.filter((r) => r.key.trim()).map((r) => [r.key.trim(), r.value]));

export function TapEditor({ tap }: { tap?: Tap }) {
  const router = useRouter();
  const qc = useQueryClient();

  const [id, setId] = useState<string | null>(tap?.id ?? null);
  const [name, setName] = useState(tap?.name ?? "");
  const [url, setUrl] = useState(tap?.url ?? "");
  const [method, setMethod] = useState(tap?.method ?? "GET");
  const [recordsPath, setRecordsPath] = useState(tap?.records_path ?? "");
  const [headers, setHeaders] = useState<KV[]>(toRows(tap?.headers));
  const [params, setParams] = useState<KV[]>(toRows(tap?.query_params));
  const [body, setBody] = useState("");
  const [hasBody] = useState(tap?.has_body ?? false);
  const [destSel, setDestSel] = useState<Set<string>>(new Set(tap?.dest_connection_ids ?? []));
  const [destTable, setDestTable] = useState(tap?.dest_table ?? "");
  const [writeMode, setWriteMode] = useState(tap?.write_mode ?? "append");
  const [test, setTest] = useState<TapTestResult | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);

  const connections = useQuery({ queryKey: ["connections"], queryFn: api.listConnections });
  const job = useJob(jobId);
  const runs = useQuery({
    queryKey: ["tap-runs", id],
    queryFn: () => api.listTapRuns(id!),
    enabled: !!id,
  });

  useEffect(() => {
    if (job.data?.status === "complete") {
      qc.invalidateQueries({ queryKey: ["tap-runs", id] });
      qc.invalidateQueries({ queryKey: ["taps"] });
    }
  }, [job.data?.status, id, qc]);

  const bodyAllowed = method !== "GET";
  const configBody = (): string | undefined => (body.trim() ? body : undefined);
  const writeBody = () => ({
    name,
    url,
    method,
    records_path: recordsPath,
    headers: toObj(headers),
    query_params: toObj(params),
    ...(configBody() !== undefined ? { body: configBody() } : {}),
    dest_connection_ids: Array.from(destSel),
    dest_table: destTable,
    write_mode: writeMode,
  });

  const persist = async (): Promise<string> => {
    if (!name.trim()) throw new Error("Give the tap a name");
    if (!url.trim()) throw new Error("Enter an endpoint URL");
    const saved = id ? await api.updateTap(id, writeBody()) : await api.createTap(writeBody());
    if (!id) {
      setId(saved.id);
      window.history.replaceState(null, "", `/taps/${saved.id}`);
    }
    qc.setQueryData(["tap", saved.id], saved);
    return saved.id;
  };

  const saveMut = useMutation({
    mutationFn: persist,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["taps"] });
      toast.success("Saved");
    },
    onError: (e) => toast.error(String(e)),
  });

  const testMut = useMutation({
    mutationFn: () =>
      api.testTap({
        url,
        method,
        records_path: recordsPath,
        headers: toObj(headers),
        query_params: toObj(params),
        body: configBody() ?? null,
      }),
    onSuccess: (r) => setTest(r),
    onError: (e) => toast.error(String(e)),
  });

  const fetchMut = useMutation({
    mutationFn: async () => {
      const tid = await persist();
      return api.fetchTap(tid);
    },
    onSuccess: (r) => {
      setJobId(r.job_id);
      toast.success("Fetch started");
    },
    onError: (e) => toast.error(String(e)),
  });

  const deleteMut = useMutation({
    mutationFn: () => api.deleteTap(id!),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["taps"] });
      toast.success("Deleted");
      router.push("/taps");
    },
    onError: (e) => toast.error(String(e)),
  });

  const fetching = fetchMut.isPending || (!!jobId && job.data?.status !== "complete");
  const canSave = !!name.trim() && !!url.trim();

  return (
    <div>
      <PageHeader
        title={id ? "Edit tap" : "New tap"}
        description="Pull JSON from a REST endpoint and land each record as a JSONB row in your destination database(s). No destination = preview only."
        breadcrumbs={[{ label: "Taps", href: "/taps" }, { label: id ? name || "Tap" : "New" }]}
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
            <Button onClick={() => fetchMut.mutate()} disabled={!canSave || fetching}>
              {fetching ? <Loader2 className="h-4 w-4 mr-1.5 animate-spin" /> : <Play className="h-4 w-4 mr-1.5" />}
              Fetch now
            </Button>
          </div>
        }
      />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_22rem]">
        {/* Config */}
        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="tap-name">Name</Label>
            <Input id="tap-name" placeholder="e.g. Weather API" value={name} onChange={(e) => setName(e.target.value)} />
          </div>

          <div className="grid gap-3 sm:grid-cols-[7rem_1fr]">
            <div className="space-y-1.5">
              <Label>Method</Label>
              <Select value={method} onValueChange={(v) => setMethod(v as Tap["method"])}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {METHODS.map((m) => (
                    <SelectItem key={m} value={m}>{m}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="tap-url">URL</Label>
              <Input id="tap-url" className="font-mono text-sm" placeholder="https://api.example.com/v1/items" value={url} onChange={(e) => setUrl(e.target.value)} />
            </div>
          </div>

          <KeyValueEditor label="Headers" hint="e.g. Authorization: Bearer …, x-api-key: …" rows={headers} onChange={setHeaders} />
          <KeyValueEditor label="Query params" rows={params} onChange={setParams} />

          {bodyAllowed && (
            <div className="space-y-1.5">
              <Label htmlFor="tap-body">Request body</Label>
              <Textarea
                id="tap-body"
                className="min-h-[5rem] font-mono text-xs"
                placeholder={hasBody ? "(a body is set — type to replace it)" : '{"query": "…"}'}
                value={body}
                onChange={(e) => setBody(e.target.value)}
              />
            </div>
          )}

          <div className="space-y-1.5">
            <Label htmlFor="tap-records">Records path <span className="text-muted-foreground">(optional)</span></Label>
            <Input id="tap-records" className="font-mono text-sm" placeholder="e.g. data.items — blank = whole response" value={recordsPath} onChange={(e) => setRecordsPath(e.target.value)} />
            <p className="text-xs text-muted-foreground">Dot path to the array of records. Blank uses the root (array → rows, object → one row).</p>
          </div>
        </div>

        {/* Destinations + run */}
        <div className="space-y-4">
          <Card className="h-fit">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">Destinations</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {connections.isLoading ? (
                <p className="text-sm text-muted-foreground">Loading…</p>
              ) : !connections.data?.length ? (
                <p className="text-sm text-muted-foreground">No connections yet.</p>
              ) : (
                connections.data.map((c) => (
                  <label key={c.id} className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-accent cursor-pointer">
                    <input
                      type="checkbox"
                      className="h-4 w-4 accent-primary"
                      checked={destSel.has(c.id)}
                      onChange={() =>
                        setDestSel((prev) => {
                          const n = new Set(prev);
                          if (n.has(c.id)) n.delete(c.id); else n.add(c.id);
                          return n;
                        })
                      }
                    />
                    <span className="truncate">{c.name}</span>
                  </label>
                ))
              )}
              <p className="pt-1 text-xs text-muted-foreground">
                Leave empty to just preview the response (no write).
              </p>
              {destSel.size > 0 && (
                <div className="space-y-2 border-t pt-2">
                  <div className="space-y-1.5">
                    <Label>Destination table</Label>
                    <Input className="font-mono text-sm" placeholder="public.api_weather" value={destTable} onChange={(e) => setDestTable(e.target.value)} />
                  </div>
                  <div className="space-y-1.5">
                    <Label>Write mode</Label>
                    <Select value={writeMode} onValueChange={(v) => setWriteMode(v as Tap["write_mode"])}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="append">Append (accumulate)</SelectItem>
                        <SelectItem value="replace">Replace (truncate + load)</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Auto-creates <code className="font-mono">{destTable || "table"}</code> as (id, fetched_at, source, data jsonb).
                  </p>
                </div>
              )}
            </CardContent>
          </Card>

        </div>
      </div>

      {/* Full-width preview so the JSON isn't cramped in the side column. */}
      <Card className="mt-6">
        <CardHeader className="flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-base">Preview</CardTitle>
          <Button variant="outline" size="sm" onClick={() => testMut.mutate()} disabled={!url.trim() || testMut.isPending}>
            {testMut.isPending ? <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" /> : <FlaskConical className="h-3.5 w-3.5 mr-1" />}
            Test
          </Button>
        </CardHeader>
        <CardContent>
          {test ? (
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-sm">
                {test.ok ? <CheckCircle2 className="h-4 w-4 text-emerald-500" /> : <XCircle className="h-4 w-4 text-destructive" />}
                {test.ok ? `HTTP ${test.http_status} · ${test.record_count} record(s)` : "Failed"}
              </div>
              {test.error && <p className="font-mono text-xs text-destructive">{test.error}</p>}
              {test.ok && (
                <pre className="max-h-[32rem] w-full overflow-auto rounded-md border bg-muted px-3 py-2 font-mono text-xs leading-relaxed">
                  {JSON.stringify(test.sample, null, 2)}
                </pre>
              )}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              Click <span className="font-medium">Test</span> to fetch and preview the JSON structure (nothing is saved).
            </p>
          )}
        </CardContent>
      </Card>

      {id && runs.data && runs.data.length > 0 && (
        <Card className="mt-6">
          <CardHeader className="pb-2"><CardTitle className="text-base">Fetch history</CardTitle></CardHeader>
          <CardContent>
            <ul className="space-y-2">
              {runs.data.slice(0, 10).map((r) => <RunRow key={r.id} run={r} />)}
            </ul>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function KeyValueEditor({ label, hint, rows, onChange }: { label: string; hint?: string; rows: KV[]; onChange: (r: KV[]) => void }) {
  const set = (i: number, patch: Partial<KV>) => onChange(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  return (
    <div className="space-y-1.5">
      <Label>{label}</Label>
      <div className="space-y-1.5">
        {rows.map((r, i) => (
          <div key={i} className="flex gap-2">
            <Input className="font-mono text-xs" placeholder="key" value={r.key} onChange={(e) => set(i, { key: e.target.value })} />
            <Input className="font-mono text-xs" placeholder="value" value={r.value} onChange={(e) => set(i, { value: e.target.value })} />
            <Button variant="ghost" size="icon" className="h-9 w-9 shrink-0" onClick={() => onChange(rows.filter((_, j) => j !== i))}>
              <Trash2 className="h-4 w-4 text-muted-foreground" />
            </Button>
          </div>
        ))}
        <Button variant="outline" size="sm" onClick={() => onChange([...rows, { key: "", value: "" }])}>
          <Plus className="h-3.5 w-3.5 mr-1" /> Add {label.toLowerCase().replace(/s$/, "")}
        </Button>
      </div>
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

function RunRow({ run }: { run: TapRun }) {
  const variant = run.status === "succeeded" ? "success" : run.status === "failed" ? "destructive" : "secondary";
  return (
    <li className="rounded-md border p-2 text-sm">
      <div className="flex items-center justify-between gap-2">
        <span className="tabular-nums">{new Date(run.started_at).toLocaleString()}</span>
        <Badge variant={variant}>{run.status}</Badge>
      </div>
      <div className="mt-0.5 text-xs text-muted-foreground">
        {run.record_count ?? 0} record(s){run.http_status ? ` · HTTP ${run.http_status}` : ""}
        {run.summary.length > 0 && ` · ${run.summary.map((s) => `${s.connection_name}: ${s.ok ? `${s.rows_written} rows` : "fail"}`).join(", ")}`}
      </div>
      {run.error && <p className="mt-1 font-mono text-xs text-destructive">{run.error}</p>}
    </li>
  );
}
