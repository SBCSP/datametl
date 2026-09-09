"use client";

import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import type { TenantKind } from "@/lib/types";
import { isValidSlug, slugifyName } from "@/lib/slug";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

/** Blocking first-workspace modal — cannot dismiss until onboard succeeds. */
export function OnboardingModal() {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [slugTouched, setSlugTouched] = useState(false);
  const [kind, setKind] = useState<TenantKind>("personal");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!slugTouched) setSlug(slugifyName(name));
  }, [name, slugTouched]);

  const create = useMutation({
    mutationFn: () =>
      api.createTenant({
        name: name.trim(),
        slug: slug.trim().toLowerCase(),
        kind,
      }),
    onSuccess: async () => {
      setError(null);
      await qc.invalidateQueries({ queryKey: ["tenants-me"] });
    },
    onError: (err: unknown) => {
      const msg =
        err && typeof err === "object" && "body" in err
          ? String((err as { body: string }).body)
          : "Could not create workspace.";
      setError(msg);
    },
  });

  const slugOk = isValidSlug(slug.trim().toLowerCase());
  const canSubmit = name.trim().length > 0 && slugOk && !create.isPending;

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/80 px-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="onboard-title"
        className="w-full max-w-md rounded-lg border bg-background p-6 shadow-lg"
      >
        <h2 id="onboard-title" className="text-lg font-semibold tracking-tight">
          Create your workspace
        </h2>
        <p className="mt-1.5 text-sm text-muted-foreground">
          DataMETL needs a workspace before you can continue. Cutover bind alone does not
          count — pick a name and slug to get started.
        </p>

        <form
          className="mt-5 space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (!canSubmit) return;
            create.mutate();
          }}
        >
          <div className="space-y-2">
            <Label htmlFor="onboard-name">Name</Label>
            <Input
              id="onboard-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Acme Corp"
              autoFocus
              required
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="onboard-slug">Slug</Label>
            <Input
              id="onboard-slug"
              value={slug}
              onChange={(e) => {
                setSlugTouched(true);
                setSlug(e.target.value.toLowerCase());
              }}
              placeholder="acme-corp"
              required
            />
            <p className="text-xs text-muted-foreground">
              Lowercase letters, numbers, and hyphens only.
            </p>
            {slug && !slugOk && (
              <p className="text-xs text-destructive">Invalid slug format.</p>
            )}
          </div>

          <div className="space-y-2">
            <Label>Kind</Label>
            <Select value={kind} onValueChange={(v) => setKind(v as TenantKind)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="personal">Personal</SelectItem>
                <SelectItem value="organization">Organization</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {error && (
            <p className="break-words text-sm text-destructive">{error}</p>
          )}

          <Button type="submit" className="w-full" disabled={!canSubmit}>
            {create.isPending ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Creating…
              </>
            ) : (
              "Create workspace"
            )}
          </Button>
        </form>
      </div>
    </div>
  );
}
