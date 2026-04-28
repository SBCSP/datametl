"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { Upload } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { PageHeader } from "@/components/page-header";

const SSL_MODES = ["disable", "allow", "prefer", "require", "verify-ca", "verify-full"] as const;
type SslMode = (typeof SSL_MODES)[number];

export default function NewConnectionPage() {
  const router = useRouter();
  const certFileInput = useRef<HTMLInputElement>(null);
  const [form, setForm] = useState({
    name: "",
    host: "host.docker.internal",
    port: 5432,
    database: "",
    user: "postgres",
    password: "",
    sslmode: "" as SslMode | "",
    sslrootcert: "",
  });
  const set = <K extends keyof typeof form>(k: K, v: (typeof form)[K]) => setForm((f) => ({ ...f, [k]: v }));

  const wantsCert = form.sslmode === "verify-ca" || form.sslmode === "verify-full";

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

  const create = useMutation({
    mutationFn: () =>
      api.createConnection({
        name: form.name,
        engine: "postgres",
        credentials: {
          host: form.host,
          port: Number(form.port),
          database: form.database,
          user: form.user,
          password: form.password,
          sslmode: form.sslmode || undefined,
          sslrootcert: wantsCert && form.sslrootcert ? form.sslrootcert : undefined,
        },
      }),
    onSuccess: (c) => {
      toast.success(`Created "${c.name}"`);
      router.push("/connections");
    },
    onError: (e) => toast.error(String(e)),
  });

  const valid =
    form.name &&
    form.database &&
    form.password &&
    (!wantsCert || form.sslrootcert.includes("-----BEGIN CERTIFICATE-----"));

  return (
    <div>
      <PageHeader
        title="New connection"
        description="Postgres credentials are encrypted at rest with Fernet."
        breadcrumbs={[{ label: "Connections", href: "/connections" }, { label: "New" }]}
      />
      <div className="max-w-3xl">
        <Card>
          <CardHeader>
            <CardTitle>Postgres</CardTitle>
            <CardDescription>
              For Supabase, point at the project's pooler host on port 6543 or direct on 5432.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid grid-cols-2 gap-4">
            <Field label="Name" col2>
              <Input value={form.name} onChange={(e) => set("name", e.target.value)} placeholder="prod-supabase" />
            </Field>
            <Field label="Host">
              <Input value={form.host} onChange={(e) => set("host", e.target.value)} />
            </Field>
            <Field label="Port">
              <Input type="number" value={form.port} onChange={(e) => set("port", Number(e.target.value))} />
            </Field>
            <Field label="Database" col2>
              <Input value={form.database} onChange={(e) => set("database", e.target.value)} placeholder="postgres" />
            </Field>
            <Field label="User">
              <Input value={form.user} onChange={(e) => set("user", e.target.value)} />
            </Field>
            <Field label="Password">
              <Input
                type="password"
                value={form.password}
                onChange={(e) => set("password", e.target.value)}
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
              <p className="text-xs text-muted-foreground">
                AWS RDS: use <code className="font-mono">verify-full</code> with the global root CA bundle. Supabase
                works with <code className="font-mono">require</code>.
              </p>
            </Field>

            {wantsCert && (
              <Field label="SSL root certificate (PEM)" col2>
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
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => certFileInput.current?.click()}
                    >
                      <Upload className="h-4 w-4" /> Upload .pem
                    </Button>
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
              </Field>
            )}

            <div className="col-span-2 flex justify-end gap-2 pt-2">
              <Button variant="ghost" onClick={() => router.back()}>
                Cancel
              </Button>
              <Button onClick={() => create.mutate()} disabled={!valid || create.isPending}>
                Save
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
