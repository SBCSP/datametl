"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { CheckCircle2, Loader2, Pencil, Play, Save, Sparkles, Trash2, XCircle } from "lucide-react";
import { api, streamDescribeSql } from "@/lib/api";
import type { ConnectionRunResult, ScriptRunResult, SqlScript, StatementResult } from "@/lib/types";
import { useJob } from "@/lib/use-job";
import { Markdown } from "@/components/markdown";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { PageHeader } from "@/components/page-header";

/** Editor + multi-connection runner for a single SQL script. Used by both the "new" page
 * (no `script` prop) and the "[id]" page. Running always persists the current name/content
 * first, so the backend executes exactly what's on screen. */
export function ScriptEditor({ script }: { script?: SqlScript }) {
  const router = useRouter();
  const qc = useQueryClient();

  const [id, setId] = useState<string | null>(script?.id ?? null);
  const [name, setName] = useState(script?.name ?? "");
  const [description, setDescription] = useState(script?.description ?? "");
  const [editingDesc, setEditingDesc] = useState(false);
  const [descSnapshot, setDescSnapshot] = useState(script?.description ?? "");
  const [generating, setGenerating] = useState(false);
  const genAbort = useRef<AbortController | null>(null);
  const [content, setContent] = useState(script?.content ?? "");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [allowWrites, setAllowWrites] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);

  // Abort any in-flight description generation if the editor unmounts.
  useEffect(() => () => genAbort.current?.abort(), []);

  // Read the current SQL and let Mel stream a description into the field (edit mode, so the
  // operator reviews/tweaks before saving).
  async function generateDescription() {
    if (!content.trim()) {
      toast.error("Write some SQL first — there's nothing to describe.");
      return;
    }
    genAbort.current?.abort();
    const ctrl = new AbortController();
    genAbort.current = ctrl;
    setDescSnapshot(description);
    setDescription("");
    setEditingDesc(true);
    setGenerating(true);
    try {
      await streamDescribeSql(content, {
        signal: ctrl.signal,
        onToken: (chunk) => setDescription((prev) => prev + chunk),
      });
    } catch (e) {
      if ((e as Error)?.name !== "AbortError") {
        toast.error(`Mel couldn't generate a description: ${String(e)}`);
        setDescription(descSnapshot); // restore on failure
      }
    } finally {
      setGenerating(false);
    }
  }

  const connections = useQuery({ queryKey: ["connections"], queryFn: api.listConnections });
  const job = useJob(jobId);

  // Create-or-update, returning the persisted id. Run/Save both go through this.
  const persist = async (): Promise<string> => {
    if (!name.trim()) throw new Error("Give the script a name first");
    const saved = id
      ? await api.updateScript(id, { name, content, description })
      : await api.createScript({ name, content, description });
    if (!id) {
      setId(saved.id);
      // Make the URL shareable without remounting (which would drop selection / job state).
      window.history.replaceState(null, "", `/scripts/${saved.id}`);
    }
    // Keep the detail query cache in sync so navigating back to this script shows the saved
    // values instead of the pre-edit copy the editor would otherwise re-seed from.
    qc.setQueryData(["script", saved.id], saved);
    return saved.id;
  };

  const saveMut = useMutation({
    mutationFn: persist,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["scripts"] });
      toast.success("Saved");
    },
    onError: (e) => toast.error(String(e)),
  });

  const runMut = useMutation({
    mutationFn: async () => {
      const sid = await persist();
      return api.runScript(sid, Array.from(selected), allowWrites);
    },
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["scripts"] });
      setJobId(r.job_id);
    },
    onError: (e) => toast.error(String(e)),
  });

  const deleteMut = useMutation({
    mutationFn: () => api.deleteScript(id!),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["scripts"] });
      toast.success("Deleted");
      router.push("/scripts");
    },
    onError: (e) => toast.error(String(e)),
  });

  const toggle = (cid: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(cid)) next.delete(cid);
      else next.add(cid);
      return next;
    });
  };

  const jobStatus = job.data?.status;
  const polling = !!jobId && jobStatus !== "complete" && jobStatus !== "not_found";
  const running = runMut.isPending || polling;
  const result = jobStatus === "complete" ? (job.data?.result as ScriptRunResult | null) : null;
  const jobError = jobStatus === "complete" ? job.data?.error : null;

  const canRun = !!name.trim() && selected.size > 0 && !running;

  return (
    <div>
      <PageHeader
        title={id ? "Edit script" : "New script"}
        description="Write SQL, then run it against one or many connections at once. Runs read-only by default (rolled back); enable “Allow writes” to commit updates/DDL — atomically per connection."
        breadcrumbs={[{ label: "SQL Scripts", href: "/scripts" }, { label: id ? name || "Script" : "New" }]}
        actions={
          <div className="flex gap-2">
            {id && (
              <Button variant="outline" onClick={() => deleteMut.mutate()} disabled={deleteMut.isPending}>
                <Trash2 className="h-4 w-4 mr-1.5" /> Delete
              </Button>
            )}
            <Button variant="outline" onClick={() => saveMut.mutate()} disabled={!name.trim() || saveMut.isPending}>
              <Save className="h-4 w-4 mr-1.5" /> Save
            </Button>
            <Button
              variant={allowWrites ? "destructive" : "default"}
              onClick={() => runMut.mutate()}
              disabled={!canRun}
            >
              {running ? <Loader2 className="h-4 w-4 mr-1.5 animate-spin" /> : <Play className="h-4 w-4 mr-1.5" />}
              {allowWrites ? "Run writes" : "Run"}
              {selected.size > 0 ? ` (${selected.size})` : ""}
            </Button>
          </div>
        }
      />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_18rem]">
        {/* Editor */}
        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="script-name">Name</Label>
            <Input
              id="script-name"
              placeholder="e.g. Row counts by table"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <Label htmlFor="script-description">Description</Label>
              <div className="flex items-center gap-1">
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 px-2 text-xs"
                  onClick={generateDescription}
                  disabled={generating || !content.trim()}
                  title="Read the current SQL and let Mel write a description"
                >
                  {generating ? (
                    <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" />
                  ) : (
                    <Sparkles className="h-3.5 w-3.5 mr-1" />
                  )}
                  {generating ? "Generating…" : "Generate with Mel"}
                </Button>
                {!editingDesc && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 px-2 text-xs"
                    onClick={() => {
                      setDescSnapshot(description);
                      setEditingDesc(true);
                    }}
                  >
                    <Pencil className="h-3.5 w-3.5 mr-1" /> Edit
                  </Button>
                )}
              </div>
            </div>

            {editingDesc ? (
              <div className="space-y-2">
                <Textarea
                  id="script-description"
                  className="min-h-[6rem] text-sm leading-relaxed"
                  placeholder="What does this script do? Markdown supported (headings, lists, **bold**, `code`)."
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  autoFocus
                />
                <div className="flex items-center gap-2">
                  <Button
                    size="sm"
                    disabled={generating}
                    onClick={() => {
                      setEditingDesc(false);
                      // Persist immediately when the script already exists; for a brand-new,
                      // unsaved script just render it and let the big Save commit everything.
                      if (id && name.trim()) saveMut.mutate();
                    }}
                  >
                    <Save className="h-3.5 w-3.5 mr-1" /> Save description
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      genAbort.current?.abort(); // stop streaming if mid-generation
                      setDescription(descSnapshot);
                      setEditingDesc(false);
                    }}
                  >
                    Cancel
                  </Button>
                  {generating && (
                    <span className="text-xs text-muted-foreground">Mel is writing…</span>
                  )}
                </div>
              </div>
            ) : description.trim() ? (
              <div
                className="rounded-md border bg-muted/30 px-3 py-2"
                onDoubleClick={() => {
                  setDescSnapshot(description);
                  setEditingDesc(true);
                }}
                title="Double-click to edit"
              >
                <Markdown>{description}</Markdown>
              </div>
            ) : (
              <button
                type="button"
                onClick={() => {
                  setDescSnapshot(description);
                  setEditingDesc(true);
                }}
                className="w-full rounded-md border border-dashed px-3 py-3 text-left text-sm text-muted-foreground hover:bg-accent hover:text-foreground"
              >
                Add a description…
              </button>
            )}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="script-sql">SQL</Label>
            <Textarea
              id="script-sql"
              className="min-h-[18rem] font-mono text-xs leading-relaxed"
              placeholder={"SELECT count(*) FROM public.users;\nSELECT count(*) FROM public.orders;"}
              value={content}
              onChange={(e) => setContent(e.target.value)}
              spellCheck={false}
            />
            <p className="text-xs text-muted-foreground">
              Separate statements with semicolons. Results are shown per statement, per connection
              (up to 1000 rows each).
            </p>
          </div>
        </div>

        {/* Connection picker */}
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

            {/* Write mode toggle */}
            <label className="mt-2 flex items-start gap-2 rounded-md border border-dashed px-2 py-2 text-xs cursor-pointer">
              <input
                type="checkbox"
                className="mt-0.5 h-4 w-4 accent-destructive"
                checked={allowWrites}
                onChange={(e) => setAllowWrites(e.target.checked)}
              />
              <span>
                <span className="font-medium text-foreground">Allow writes (commits changes)</span>
                <span className="mt-0.5 block text-muted-foreground">
                  Off = read-only (rolled back). On = runs in a transaction and commits; rolls back
                  if any statement fails. Applies to every selected connection.
                </span>
              </span>
            </label>
          </CardContent>
        </Card>
      </div>

      {/* Results */}
      <div className="mt-8 space-y-4">
        {running && (
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> Running across {selected.size} connection
            {selected.size === 1 ? "" : "s"}…
          </p>
        )}

        {jobError && (
          <Alert variant="destructive">
            <AlertDescription>{jobError}</AlertDescription>
          </Alert>
        )}

        {result && result.connections.length > 0 && (
          <div className="flex gap-4 overflow-x-auto pb-2">
            {result.connections.map((conn) => (
              <ConnectionResult key={conn.connection_id} conn={conn} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function ConnectionResult({ conn }: { conn: ConnectionRunResult }) {
  return (
    <Card className="flex-1 min-w-[22rem]">
      <CardHeader className="flex-row items-center justify-between space-y-0 gap-2">
        <CardTitle className="text-sm flex items-center gap-2">
          {conn.ok ? (
            <CheckCircle2 className="h-4 w-4 text-emerald-500" />
          ) : (
            <XCircle className="h-4 w-4 text-destructive" />
          )}
          {conn.connection_name}
        </CardTitle>
        <Badge variant={conn.ok ? "success" : "destructive"}>{conn.ok ? "ok" : "error"}</Badge>
      </CardHeader>
      <CardContent className="space-y-4">
        {conn.error && (
          <Alert variant="destructive">
            <AlertDescription>{conn.error}</AlertDescription>
          </Alert>
        )}
        {conn.statements.map((s) => (
          <StatementBlock key={s.index} stmt={s} />
        ))}
        {!conn.error && conn.statements.length === 0 && (
          <p className="text-sm text-muted-foreground">No statements in this script.</p>
        )}
      </CardContent>
    </Card>
  );
}

function StatementBlock({ stmt }: { stmt: StatementResult }) {
  return (
    <div className="space-y-1.5">
      <pre className="overflow-x-auto rounded-md bg-muted px-3 py-2 text-xs font-mono text-muted-foreground">
        {stmt.sql}
      </pre>

      {stmt.kind === "error" ? (
        <Alert variant="destructive">
          <AlertDescription className="font-mono text-xs">{stmt.error}</AlertDescription>
        </Alert>
      ) : stmt.kind === "command" ? (
        <p className="text-xs text-muted-foreground">
          OK — {stmt.row_count} row{stmt.row_count === 1 ? "" : "s"} affected · {stmt.duration_ms}ms
        </p>
      ) : (
        <>
          <div className="overflow-x-auto rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  {stmt.columns.map((col, i) => (
                    <TableHead key={i} className="whitespace-nowrap font-mono text-xs">
                      {col}
                    </TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {stmt.rows.map((row, ri) => (
                  <TableRow key={ri}>
                    {row.map((cell, ci) => (
                      <TableCell key={ci} className="whitespace-nowrap font-mono text-xs">
                        {renderCell(cell)}
                      </TableCell>
                    ))}
                  </TableRow>
                ))}
                {stmt.rows.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={Math.max(stmt.columns.length, 1)} className="text-xs text-muted-foreground">
                      (0 rows)
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
          <p className="text-xs text-muted-foreground">
            {stmt.row_count} row{stmt.row_count === 1 ? "" : "s"} · {stmt.duration_ms}ms
            {stmt.truncated && " · truncated to first 1000"}
          </p>
        </>
      )}
    </div>
  );
}

function renderCell(value: unknown): React.ReactNode {
  if (value === null || value === undefined) {
    return <span className="italic text-muted-foreground/60">NULL</span>;
  }
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
