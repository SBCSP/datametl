"use client";

import { use, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { Mapping } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { PageHeader } from "@/components/page-header";

export default function MappingsPage({ params }: { params: Promise<{ comparisonId: string }> }) {
  const { comparisonId } = use(params);
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["mappings", comparisonId],
    queryFn: () => api.listMappings(comparisonId),
  });

  const update = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Partial<Mapping> }) =>
      api.updateMapping(comparisonId, id, body),
    onSuccess: () => {
      toast.success("Saved");
      qc.invalidateQueries({ queryKey: ["mappings", comparisonId] });
    },
    onError: (e) => toast.error(String(e)),
  });

  const groups = (data ?? []).reduce<Record<string, Mapping[]>>((acc, m) => {
    (acc[m.source_table] ??= []).push(m);
    return acc;
  }, {});

  const lossyCount = (data ?? []).filter((m) => m.is_lossy).length;

  return (
    <div>
      <PageHeader
        title="Mappings"
        description={
          <span>
            <span className="font-mono text-xs">{comparisonId}</span>
            {data?.length ? (
              <span className="ml-3">
                {data.length} columns · {lossyCount > 0 && (
                  <Badge variant="destructive" className="ml-1">{lossyCount} lossy</Badge>
                )}
              </span>
            ) : null}
          </span>
        }
        breadcrumbs={[{ label: "Mappings", href: "/mappings" }, { label: comparisonId.slice(0, 8) + "…" }]}
      />

      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : !data?.length ? (
        <p className="text-sm text-muted-foreground">No mappings yet — comparison may still be running.</p>
      ) : (
        <div className="space-y-6">
          {Object.entries(groups).map(([table, rows]) => (
            <Card key={table}>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-mono">{table}</CardTitle>
              </CardHeader>
              <CardContent className="p-0">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Source column</TableHead>
                      <TableHead>Source type</TableHead>
                      <TableHead>Default dest type</TableHead>
                      <TableHead>Override</TableHead>
                      <TableHead></TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {rows.map((m) => (
                      <MappingRow
                        key={m.id}
                        m={m}
                        onSave={(override) => update.mutate({ id: m.id, body: { override_dest_type: override } })}
                      />
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

function MappingRow({ m, onSave }: { m: Mapping; onSave: (override: string | null) => void }) {
  const [draft, setDraft] = useState(m.override_dest_type ?? "");
  const dirty = draft !== (m.override_dest_type ?? "");
  return (
    <TableRow>
      <TableCell className="font-mono">{m.source_column}</TableCell>
      <TableCell className="font-mono text-xs">{m.source_type}</TableCell>
      <TableCell className="font-mono text-xs">
        {m.default_dest_type}
        {m.is_lossy && (
          <Badge className="ml-2" variant="destructive">
            lossy
          </Badge>
        )}
      </TableCell>
      <TableCell>
        <Input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="(use default)"
          className="font-mono text-xs"
        />
      </TableCell>
      <TableCell className="text-right">
        <Button
          size="sm"
          variant={dirty ? "default" : "ghost"}
          disabled={!dirty}
          onClick={() => onSave(draft || null)}
        >
          Save
        </Button>
      </TableCell>
    </TableRow>
  );
}
