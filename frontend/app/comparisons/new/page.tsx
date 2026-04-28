"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { ArrowRight } from "lucide-react";
import { api } from "@/lib/api";
import type { SchemaSummary, SnapshotSummary } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { PageHeader } from "@/components/page-header";

const ALL = "__all__"; // sentinel value for "no schema filter"

export default function NewComparisonPage() {
  const router = useRouter();
  const connections = useQuery({ queryKey: ["connections"], queryFn: api.listConnections });

  const [sourceConnId, setSourceConnId] = useState("");
  const [destConnId, setDestConnId] = useState("");
  const [sourceSnapId, setSourceSnapId] = useState("");
  const [destSnapId, setDestSnapId] = useState("");
  const [sourceSchemaName, setSourceSchemaName] = useState(ALL);
  const [destSchemaName, setDestSchemaName] = useState(ALL);

  const sourceSnaps = useQuery({
    queryKey: ["snapshots", sourceConnId],
    queryFn: () => api.listSnapshots(sourceConnId),
    enabled: !!sourceConnId,
  });
  const destSnaps = useQuery({
    queryKey: ["snapshots", destConnId],
    queryFn: () => api.listSnapshots(destConnId),
    enabled: !!destConnId,
  });

  const sourceSchemas = useQuery({
    queryKey: ["snapshot-schemas", sourceSnapId],
    queryFn: () => api.getSnapshotSchemas(sourceSnapId),
    enabled: !!sourceSnapId,
  });
  const destSchemas = useQuery({
    queryKey: ["snapshot-schemas", destSnapId],
    queryFn: () => api.getSnapshotSchemas(destSnapId),
    enabled: !!destSnapId,
  });

  // If user picks a schema on one side, require it on the other (the backend rejects asymmetric scope).
  const scopeAsymmetric =
    (sourceSchemaName !== ALL && destSchemaName === ALL) ||
    (sourceSchemaName === ALL && destSchemaName !== ALL);

  const create = useMutation({
    mutationFn: () =>
      api.createComparison({
        source_snapshot_id: sourceSnapId,
        dest_snapshot_id: destSnapId,
        source_schema: sourceSchemaName === ALL ? null : sourceSchemaName,
        dest_schema: destSchemaName === ALL ? null : destSchemaName,
      }),
    onSuccess: (r) => {
      toast.success("Comparison started");
      router.push(`/comparisons/${r.comparison_id}?job=${encodeURIComponent(r.job_id)}`);
    },
    onError: (e) => toast.error(String(e)),
  });

  return (
    <div>
      <PageHeader
        title="New comparison"
        description="Pick a source snapshot, a destination snapshot, and optionally scope the diff to a single schema on each side."
        breadcrumbs={[{ label: "Comparisons", href: "/comparisons" }, { label: "New" }]}
      />

      <div className="space-y-6">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-[1fr_auto_1fr] md:items-stretch">
          <Side
            title="Source"
            connId={sourceConnId}
            setConnId={(v) => {
              setSourceConnId(v);
              setSourceSnapId("");
              setSourceSchemaName(ALL);
            }}
            snapId={sourceSnapId}
            setSnapId={(v) => {
              setSourceSnapId(v);
              setSourceSchemaName(ALL);
            }}
            schemaName={sourceSchemaName}
            setSchemaName={setSourceSchemaName}
            connections={connections.data}
            snapshots={sourceSnaps.data}
            schemas={sourceSchemas.data}
          />
          <ArrowRight className="hidden md:block h-6 w-6 text-muted-foreground self-center mx-auto" />
          <Side
            title="Destination"
            connId={destConnId}
            setConnId={(v) => {
              setDestConnId(v);
              setDestSnapId("");
              setDestSchemaName(ALL);
            }}
            snapId={destSnapId}
            setSnapId={(v) => {
              setDestSnapId(v);
              setDestSchemaName(ALL);
            }}
            schemaName={destSchemaName}
            setSchemaName={setDestSchemaName}
            connections={connections.data}
            snapshots={destSnaps.data}
            schemas={destSchemas.data}
          />
        </div>

        {scopeAsymmetric && (
          <p className="text-sm text-amber-700 dark:text-amber-400">
            Pick a schema on both sides, or leave both at "All schemas".
          </p>
        )}

        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={() => router.back()}>
            Cancel
          </Button>
          <Button
            onClick={() => create.mutate()}
            disabled={!sourceSnapId || !destSnapId || scopeAsymmetric || create.isPending}
          >
            Run comparison
          </Button>
        </div>
      </div>
    </div>
  );
}

function Side({
  title,
  connId,
  setConnId,
  snapId,
  setSnapId,
  schemaName,
  setSchemaName,
  connections,
  snapshots,
  schemas,
}: {
  title: string;
  connId: string;
  setConnId: (v: string) => void;
  snapId: string;
  setSnapId: (v: string) => void;
  schemaName: string;
  setSchemaName: (v: string) => void;
  connections?: { id: string; name: string }[];
  snapshots?: SnapshotSummary[];
  schemas?: SchemaSummary[];
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>Connection → snapshot → (optional) schema scope</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="space-y-1.5">
          <Label>Connection</Label>
          <Select value={connId} onValueChange={setConnId}>
            <SelectTrigger>
              <SelectValue placeholder="Choose…" />
            </SelectTrigger>
            <SelectContent>
              {connections?.map((c) => (
                <SelectItem key={c.id} value={c.id}>
                  {c.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-1.5">
          <Label>Snapshot</Label>
          <Select value={snapId} onValueChange={setSnapId} disabled={!connId || !snapshots?.length}>
            <SelectTrigger>
              <SelectValue
                placeholder={snapshots?.length ? "Choose…" : "No snapshots — introspect the connection first"}
              />
            </SelectTrigger>
            <SelectContent>
              {snapshots?.map((s) => (
                <SelectItem key={s.id} value={s.id}>
                  {new Date(s.captured_at).toLocaleString()} — {s.table_count} tables
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-1.5">
          <Label>Schema</Label>
          <Select value={schemaName} onValueChange={setSchemaName} disabled={!snapId || !schemas?.length}>
            <SelectTrigger>
              <SelectValue placeholder="(loading)" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All schemas (whole-DB diff)</SelectItem>
              {schemas?.map((s) => (
                <SelectItem key={s.name} value={s.name}>
                  {s.name} — {s.table_count} tables
                  {s.view_count > 0 && `, ${s.view_count} views`}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </CardContent>
    </Card>
  );
}
