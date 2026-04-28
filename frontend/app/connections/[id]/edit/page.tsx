"use client";

import { use, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Upload } from "lucide-react";
import { api } from "@/lib/api";
import type { PostgresCredentialsUpdate } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { PageHeader } from "@/components/page-header";

const SSL_MODES = ["disable", "allow", "prefer", "require", "verify-ca", "verify-full"] as const;
type SslMode = (typeof SSL_MODES)[number];

export default function EditConnectionPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();
  const qc = useQueryClient();
  const certFileInput = useRef<HTMLInputElement>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["connection", id],
    queryFn: () => api.getConnection(id),
  });

  const [form, setForm] = useState({
    name: "",
    host: "",
    port: 5432,
    database: "",
    user: "",
    password: "",
    sslmode: "" as SslMode | "",
    sslrootcert: "",
    replaceCert: false,
  });

  // Pre-fill once the connection loads
  useEffect(() => {
    if (!data) return;
    setForm((f) => ({
      ...f,
      name: data.name,
      host: data.redacted_credentials.host,
      port: data.redacted_credentials.port,
      database: data.redacted_credentials.database,
      user: data.redacted_credentials.user,
      sslmode: (data.redacted_credentials.sslmode as SslMode) ?? "",
    }));
  }, [data]);

  const set = <K extends keyof typeof form>(k: K, v: (typeof form)[K]) => setForm((f) => ({ ...f, [k]: v }));

  const wantsCertField = form.sslmode === "verify-ca" || form.sslmode === "verify-full";
  const showCertEditor = wantsCertField && (form.replaceCert || !data?.redacted_credentials.has_sslrootcert);

  const onCertFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (file.size > 1_000_000) {
      toast.error("Cert file too large (>1 MB).");
      return;
    }
    const text = await file.text();
    if (!text.includes("-----BEGIN CERTIFICATE-----")) {
      toast.error("That doesn't look like a PEM certificate.");
      return;
    }
    set("sslrootcert", text);
    toast.success(`Loaded ${file.name}`);
  };

  const update = useMutation({
    mutationFn: () => {
      if (!data) throw new Error("not loaded");
      const credUpdate: PostgresCredentialsUpdate = {};
      const r = data.redacted_credentials;

      if (form.host !== r.host) credUpdate.host = form.host;
      if (form.port !== r.port) credUpdate.port = Number(form.port);
      if (form.database !== r.database) credUpdate.database = form.database;
      if (form.user !== r.user) credUpdate.user = form.user;
      if ((form.sslmode || null) !== (r.sslmode ?? null)) credUpdate.sslmode = form.sslmode || undefined;
      if (form.password) credUpdate.password = form.password;
      if (showCertEditor && form.sslrootcert) credUpdate.sslrootcert = form.sslrootcert;

      const body: { name?: string; credentials?: PostgresCredentialsUpdate } = {};
      if (form.name !== data.name) body.name = form.name;
      if (Object.keys(credUpdate).length > 0) body.credentials = credUpdate;

      if (!body.name && !body.credentials) throw new Error("Nothing to update");

      return api.updateConnection(id, body);
    },
    onSuccess: () => {
      toast.success("Updated");
      qc.invalidateQueries({ queryKey: ["connection", id] });
      qc.invalidateQueries({ queryKey: ["connections"] });
      router.push("/connections");
    },
    onError: (e) => toast.error(String(e)),
  });

  if (isLoading) return <p className="text-sm text-muted-foreground">Loading…</p>;
  if (!data) return <p className="text-sm text-muted-foreground">Connection not found.</p>;

  return (
    <div>
      <PageHeader
        title="Edit connection"
        description={
          <span>
            Leave password blank to keep the existing one. Host / port / user / SSL mode update in place.
          </span>
        }
        breadcrumbs={[
          { label: "Connections", href: "/connections" },
          { label: data.name, href: `/schemas/${data.id}` },
          { label: "Edit" },
        ]}
      />
      <div className="max-w-3xl">
        <Card>
          <CardHeader>
            <CardTitle>Postgres</CardTitle>
            <CardDescription>Credentials are encrypted at rest with Fernet.</CardDescription>
          </CardHeader>
          <CardContent className="grid grid-cols-2 gap-4">
            <Field label="Name" col2>
              <Input value={form.name} onChange={(e) => set("name", e.target.value)} />
            </Field>
            <Field label="Host">
              <Input value={form.host} onChange={(e) => set("host", e.target.value)} />
            </Field>
            <Field label="Port">
              <Input type="number" value={form.port} onChange={(e) => set("port", Number(e.target.value))} />
            </Field>
            <Field label="Database" col2>
              <Input value={form.database} onChange={(e) => set("database", e.target.value)} />
            </Field>
            <Field label="User">
              <Input value={form.user} onChange={(e) => set("user", e.target.value)} />
            </Field>
            <Field label="Password (leave blank to keep)">
              <Input
                type="password"
                value={form.password}
                onChange={(e) => set("password", e.target.value)}
                placeholder="••••••••"
              />
            </Field>

            <Field label="SSL mode" col2>
              <Select value={form.sslmode} onValueChange={(v) => set("sslmode", v as SslMode)}>
                <SelectTrigger>
                  <SelectValue placeholder="(default — libpq decides)" />
                </SelectTrigger>
                <SelectContent>
                  {SSL_MODES.map((m) => (
                    <SelectItem key={m} value={m}>
                      {m}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>

            {wantsCertField && (
              <Field label="SSL root certificate (PEM)" col2>
                {data.redacted_credentials.has_sslrootcert && !form.replaceCert ? (
                  <div className="flex items-center justify-between gap-2 rounded-md border bg-muted/40 px-3 py-2">
                    <span className="text-sm flex items-center gap-2">
                      <Badge variant="success">currently set</Badge>
                      A certificate is already on file.
                    </span>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => set("replaceCert", true)}
                    >
                      Replace
                    </Button>
                  </div>
                ) : (
                  <div className="space-y-2">
                    <Textarea
                      rows={6}
                      value={form.sslrootcert}
                      onChange={(e) => set("sslrootcert", e.target.value)}
                      placeholder="-----BEGIN CERTIFICATE-----&#10;...&#10;-----END CERTIFICATE-----"
                      className="font-mono text-xs"
                    />
                    <div className="flex items-center justify-between gap-2">
                      <input
                        ref={certFileInput}
                        type="file"
                        accept=".pem,.crt,.cer,application/x-pem-file"
                        className="hidden"
                        onChange={onCertFile}
                      />
                      <div className="flex items-center gap-2">
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={() => certFileInput.current?.click()}
                        >
                          <Upload className="h-4 w-4" /> Upload .pem
                        </Button>
                        {data.redacted_credentials.has_sslrootcert && (
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            onClick={() => {
                              set("sslrootcert", "");
                              set("replaceCert", false);
                            }}
                          >
                            Cancel replace
                          </Button>
                        )}
                      </div>
                      <p className="text-xs text-muted-foreground text-right">
                        AWS RDS:{" "}
                        <a
                          href="https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem"
                          target="_blank"
                          rel="noreferrer"
                          className="underline hover:text-foreground"
                        >
                          global-bundle.pem
                        </a>
                      </p>
                    </div>
                  </div>
                )}
              </Field>
            )}

            <div className="col-span-2 flex justify-end gap-2 pt-2">
              <Button variant="ghost" onClick={() => router.back()}>
                Cancel
              </Button>
              <Button onClick={() => update.mutate()} disabled={!form.name || update.isPending}>
                Save changes
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function Field({ label, children, col2 = false }: { label: string; children: React.ReactNode; col2?: boolean }) {
  return (
    <div className={`space-y-1.5 ${col2 ? "col-span-2" : ""}`}>
      <Label>{label}</Label>
      {children}
    </div>
  );
}
