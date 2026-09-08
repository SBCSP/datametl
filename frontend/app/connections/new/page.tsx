"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { Database, Lock, Upload } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { ENGINES, engineMeta, type Engine } from "@/lib/engines";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { PageHeader } from "@/components/page-header";
import { ENVIRONMENTS, type Environment, envStyle } from "@/lib/environments";

const SSL_MODES = ["disable", "allow", "prefer", "require", "verify-ca", "verify-full"] as const;
type SslMode = (typeof SSL_MODES)[number];

export default function NewConnectionPage() {
  const router = useRouter();
  const { data: settings } = useQuery({ queryKey: ["settings"], queryFn: api.getSettings });
  const proEngines = settings?.license?.can_use_mysql_mssql ?? false;
  const certFileInput = useRef<HTMLInputElement>(null);
  const [engine, setEngine] = useState<Engine | "">("");
  const [form, setForm] = useState({
    name: "",
    host: "host.docker.internal",
    port: 5432,
    database: "",
    user: "",
    password: "",
    environment: "" as Environment | "",
    sslmode: "" as SslMode | "",
    sslrootcert: "",
  });
  const set = <K extends keyof typeof form>(k: K, v: (typeof form)[K]) => setForm((f) => ({ ...f, [k]: v }));

  const meta = engineMeta(engine);

  const pickEngine = (next: Engine) => {
    const nextMeta = engineMeta(next)!;
    const prevMeta = engineMeta(engine);
    setEngine(next);
    setForm((f) => {
      const portWasDefault = !prevMeta || f.port === prevMeta.defaultPort;
      const userWasDefault = !prevMeta || f.user === "" || f.user === prevMeta.defaultUser;
      return {
        ...f,
        port: portWasDefault ? nextMeta.defaultPort : f.port,
        user: userWasDefault ? nextMeta.defaultUser : f.user,
      };
    });
  };

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
    mutationFn: () => {
      if (!engine) throw new Error("Choose a database engine first");
      return api.createConnection({
        name: form.name,
        engine,
        environment: form.environment || undefined,
        credentials: {
          host: form.host,
          port: Number(form.port),
          database: form.database,
          user: form.user,
          password: form.password,
          sslmode: form.sslmode || undefined,
          sslrootcert: wantsCert && form.sslrootcert ? form.sslrootcert : undefined,
        },
      });
    },
    onSuccess: (c) => {
      toast.success(`Created "${c.name}"`);
      router.push("/connections");
    },
    onError: (e) => toast.error(String(e)),
  });

  const valid =
    !!engine &&
    form.name &&
    form.database &&
    form.user &&
    form.password &&
    (!wantsCert || form.sslrootcert.includes("-----BEGIN CERTIFICATE-----"));

  return (
    <div>
      <PageHeader
        title="New connection"
        description="Credentials are encrypted at rest with Fernet. Choose the database engine first."
        breadcrumbs={[{ label: "Connections", href: "/connections" }, { label: "New" }]}
      />
      <div className="max-w-3xl space-y-4">
        <Card>
          <CardHeader>
            <CardTitle>Database engine</CardTitle>
            <CardDescription>Required — pick an engine before filling credentials. MySQL and SQL Server need Pro.</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {ENGINES.map((e) => {
                const selected = engine === e.value;
                const needsPro = e.value === "mysql" || e.value === "mssql";
                const locked = needsPro && !proEngines;
                return (
                  <button
                    key={e.value}
                    type="button"
                    disabled={locked}
                    onClick={() => !locked && pickEngine(e.value)}
                    title={locked ? "Requires DataMETL Pro — activate a license in Settings" : undefined}
                    className={cn(
                      "flex flex-col items-start gap-2 rounded-lg border p-4 text-left transition-colors",
                      locked && "opacity-60 cursor-not-allowed",
                      selected
                        ? "border-primary bg-accent ring-1 ring-primary"
                        : "hover:bg-accent/50 text-muted-foreground hover:text-foreground",
                    )}
                  >
                    <div className="flex items-center gap-2">
                      <Database className={cn("h-5 w-5", selected ? "text-primary" : "")} />
                      <span className="font-medium text-foreground">{e.label}</span>
                      {needsPro && (
                        <span className="text-[10px] uppercase tracking-wide rounded bg-muted px-1.5 py-0.5 text-muted-foreground flex items-center gap-1">
                          {locked ? <Lock className="h-3 w-3" /> : null}
                          Pro
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-muted-foreground leading-relaxed">{e.description}</p>
                    <p className="text-xs font-mono text-muted-foreground">
                      default port {e.defaultPort}
                    </p>
                  </button>
                );
              })}
            </div>
          </CardContent>
        </Card>

        {meta ? (
          <Card>
            <CardHeader>
              <CardTitle>{meta.label}</CardTitle>
              <CardDescription>{meta.hostHint}</CardDescription>
            </CardHeader>
            <CardContent className="grid grid-cols-2 gap-4">
              <Field label="Name" col2>
                <Input value={form.name} onChange={(e) => set("name", e.target.value)} placeholder="prod-db" />
              </Field>
              <Field label="Environment" col2>
                <Select value={form.environment} onValueChange={(v) => set("environment", v as Environment)}>
                  <SelectTrigger>
                    <SelectValue placeholder="(none)" />
                  </SelectTrigger>
                  <SelectContent>
                    {ENVIRONMENTS.map((e) => {
                      const st = envStyle(e.value)!;
                      return (
                        <SelectItem key={e.value} value={e.value}>
                          <span className="flex items-center gap-2">
                            <span className={`h-2.5 w-2.5 rounded-full ${st.dot}`} />
                            {e.label}
                          </span>
                        </SelectItem>
                      );
                    })}
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  Color-codes this connection across the app — development (green), staging (amber), production (red).
                </p>
              </Field>
              <Field label="Host">
                <Input value={form.host} onChange={(e) => set("host", e.target.value)} />
              </Field>
              <Field label="Port">
                <Input type="number" value={form.port} onChange={(e) => set("port", Number(e.target.value))} />
              </Field>
              <Field label="Database" col2>
                <Input
                  value={form.database}
                  onChange={(e) => set("database", e.target.value)}
                  placeholder={meta.databasePlaceholder}
                />
              </Field>
              <Field label="User">
                <Input value={form.user} onChange={(e) => set("user", e.target.value)} placeholder={meta.defaultUser} />
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
                    <SelectValue
                      placeholder={
                        engine === "mysql"
                          ? "(default — driver negotiates)"
                          : engine === "mssql"
                            ? "(default — TDS/driver negotiates)"
                            : "(default — libpq decides)"
                      }
                    />
                  </SelectTrigger>
                  <SelectContent>
                    {SSL_MODES.map((m) => (
                      <SelectItem key={m} value={m}>
                        {m}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">{meta.sslHint}</p>
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
        ) : (
          <Card>
            <CardContent className="py-10 text-center text-sm text-muted-foreground">
              Select PostgreSQL or MySQL above to continue.
            </CardContent>
          </Card>
        )}
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
