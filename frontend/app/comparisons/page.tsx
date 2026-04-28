"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { GitCompareArrows, Plus } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { PageHeader } from "@/components/page-header";

export default function ComparisonsPage() {
  const { data, isLoading } = useQuery({ queryKey: ["comparisons"], queryFn: api.listComparisons });

  return (
    <div>
      <PageHeader
        title="Comparisons"
        description="Schema diffs between source and destination snapshots."
        actions={
          <Button asChild>
            <Link href="/comparisons/new">
              <Plus className="h-4 w-4" /> New comparison
            </Link>
          </Button>
        }
      />

      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : !data?.length ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16 text-center space-y-3">
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-muted">
              <GitCompareArrows className="h-6 w-6 text-muted-foreground" />
            </div>
            <div>
              <h3 className="text-base font-semibold">No comparisons yet</h3>
              <p className="text-sm text-muted-foreground mt-1 max-w-sm">
                Pick a source snapshot and a destination snapshot to see schema drift.
              </p>
            </div>
            <Button asChild>
              <Link href="/comparisons/new">
                <Plus className="h-4 w-4" /> New comparison
              </Link>
            </Button>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>ID</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead className="text-right">Open</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.map((c) => (
                  <TableRow key={c.id}>
                    <TableCell className="font-mono text-xs">{c.id}</TableCell>
                    <TableCell>{new Date(c.created_at).toLocaleString()}</TableCell>
                    <TableCell className="text-right space-x-2">
                      <Button size="sm" variant="outline" asChild>
                        <Link href={`/comparisons/${c.id}`}>Diff</Link>
                      </Button>
                      <Button size="sm" variant="outline" asChild>
                        <Link href={`/mappings/${c.id}`}>Mappings</Link>
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
