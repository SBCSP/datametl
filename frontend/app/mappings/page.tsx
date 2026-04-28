"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Workflow } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { PageHeader } from "@/components/page-header";

export default function MappingsIndexPage() {
  const { data, isLoading } = useQuery({ queryKey: ["comparisons"], queryFn: api.listComparisons });

  return (
    <div>
      <PageHeader
        title="Mappings"
        description="Pick a comparison to edit its column mappings."
      />

      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : !data?.length ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16 text-center space-y-3">
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-muted">
              <Workflow className="h-6 w-6 text-muted-foreground" />
            </div>
            <p className="text-sm text-muted-foreground">Run a comparison first to generate mappings.</p>
            <Button asChild>
              <Link href="/comparisons/new">New comparison</Link>
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-2">
          {data.map((c) => (
            <Link key={c.id} href={`/mappings/${c.id}`}>
              <Card className="hover:border-foreground/20 transition-colors">
                <CardContent className="p-4 flex items-center justify-between">
                  <div>
                    <div className="font-mono text-sm">{c.id}</div>
                    <div className="text-xs text-muted-foreground">
                      {new Date(c.created_at).toLocaleString()}
                    </div>
                  </div>
                  <Button size="sm" variant="ghost">
                    Open mappings →
                  </Button>
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
