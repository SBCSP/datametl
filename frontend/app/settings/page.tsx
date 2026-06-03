"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { CheckCircle2, ExternalLink, Lock, Server, Sparkles, XCircle } from "lucide-react";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PageHeader } from "@/components/page-header";

export default function SettingsPage() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["settings"],
    queryFn: api.getSettings,
    refetchInterval: 10_000,
  });

  const [anthropicKey, setAnthropicKey] = useState("");
  const saveKey = useMutation({
    mutationFn: (key: string) => api.updateAnthropicKey(key),
    onSuccess: (r) => {
      setAnthropicKey("");
      qc.invalidateQueries({ queryKey: ["settings"] });
      toast.success(r.anthropic_api_key_set ? "Anthropic key saved" : "Anthropic key cleared");
    },
    onError: (e) => toast.error(String(e)),
  });

  return (
    <div>
      <PageHeader
        title="Settings"
        description="App-level configuration and diagnostics. Most values are env-driven and read-only; the Anthropic API key is editable below."
      />

      {isLoading || !data ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {/* About */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">About</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              <Row label="Version">
                <Badge variant="secondary">v{data.version}</Badge>
              </Row>
              <Row label="Log level">
                <code className="text-xs">{data.log_level}</code>
              </Row>
              <div className="pt-2 border-t flex flex-wrap gap-2">
                <Button variant="outline" size="sm" asChild>
                  <a href="http://localhost:8000/docs" target="_blank" rel="noreferrer">
                    OpenAPI <ExternalLink className="h-3 w-3" />
                  </a>
                </Button>
                <Button variant="outline" size="sm" asChild>
                  <a href="http://localhost:8000/health" target="_blank" rel="noreferrer">
                    Health <ExternalLink className="h-3 w-3" />
                  </a>
                </Button>
              </div>
            </CardContent>
          </Card>

          {/* Security */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2">
                <Lock className="h-4 w-4" /> Security
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              <Row label="Encryption key">
                {data.encryption_key_set ? (
                  <Badge variant="success">
                    <CheckCircle2 className="h-3 w-3 mr-1" /> configured
                  </Badge>
                ) : (
                  <Badge variant="destructive">
                    <XCircle className="h-3 w-3 mr-1" /> missing
                  </Badge>
                )}
              </Row>
              <p className="text-xs text-muted-foreground pt-2 border-t">
                Connection credentials are encrypted at rest with Fernet using{" "}
                <code className="font-mono">ENCRYPTION_KEY</code>. To rotate, generate a new key with{" "}
                <code className="font-mono">make key</code>, replace it in <code className="font-mono">.env</code>, and
                restart the stack — but be aware: existing connections were encrypted with the old key and will need to
                be re-entered.
              </p>
            </CardContent>
          </Card>

          {/* Anthropic API key (editable, write-only) */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2">
                <Sparkles className="h-4 w-4" /> Anthropic API key
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <Row label="Status">
                {data.anthropic_api_key_set ? (
                  <Badge variant="success">
                    <CheckCircle2 className="h-3 w-3 mr-1" /> set
                  </Badge>
                ) : (
                  <Badge variant="destructive">
                    <XCircle className="h-3 w-3 mr-1" /> not set
                  </Badge>
                )}
              </Row>
              <div className="space-y-1.5">
                <Label htmlFor="anthropic-key">{data.anthropic_api_key_set ? "Replace key" : "Set key"}</Label>
                <Input
                  id="anthropic-key"
                  type="password"
                  placeholder="sk-ant-…"
                  autoComplete="off"
                  value={anthropicKey}
                  onChange={(e) => setAnthropicKey(e.target.value)}
                />
              </div>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  onClick={() => saveKey.mutate(anthropicKey)}
                  disabled={!anthropicKey.trim() || saveKey.isPending}
                >
                  Save
                </Button>
                {data.anthropic_api_key_set && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => saveKey.mutate("")}
                    disabled={saveKey.isPending}
                  >
                    Clear
                  </Button>
                )}
              </div>
              <p className="text-xs text-muted-foreground pt-2 border-t">
                Stored encrypted at rest (Fernet, same as connection credentials) and used by{" "}
                <a href="/chat" className="underline">Mel</a>, the chat assistant. Write-only — the
                value is never shown again.
              </p>
            </CardContent>
          </Card>

          {/* Worker */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2">
                <Server className="h-4 w-4" /> Worker
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              <Row label="Max parallel jobs">
                <Badge variant="outline">{data.worker_max_jobs}</Badge>
              </Row>
              <Row label="Job timeout">
                <Badge variant="outline">
                  {Math.round(data.worker_job_timeout_seconds / 60)} min
                </Badge>
              </Row>
              <Row label="Queue depth">
                <Badge variant={data.queue_depth > 0 ? "warning" : "outline"}>{data.queue_depth}</Badge>
              </Row>
              <p className="text-xs text-muted-foreground pt-2 border-t">
                arq runs in the <code className="font-mono">worker</code> container. Tail logs with{" "}
                <code className="font-mono">make logs</code>.
              </p>
            </CardContent>
          </Card>

          {/* Connections / endpoints */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Endpoints</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-xs">
              <Row label="App DB">
                <code className="font-mono break-all">{data.database_url_redacted}</code>
              </Row>
              <Row label="Redis">
                <code className="font-mono break-all">{data.redis_url_redacted}</code>
              </Row>
              <Row label="CORS">
                <span className="font-mono">{data.cors_origins.join(", ")}</span>
              </Row>
              <p className="text-xs text-muted-foreground pt-2 border-t">
                These are the values the backend booted with. Change them in <code className="font-mono">.env</code> and
                restart with <code className="font-mono">make up</code>.
              </p>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="text-muted-foreground">{label}</span>
      <span>{children}</span>
    </div>
  );
}
