"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Bot, CheckCircle2, ExternalLink, KeyRound, Lock, Server, Sparkles, XCircle } from "lucide-react";
import type { MelToolApprovalMode } from "@/lib/types";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { api, apiBaseUrl } from "@/lib/api";
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

  const saveMelApproval = useMutation({
    mutationFn: (mode: MelToolApprovalMode) => api.updateMelToolApproval(mode),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["settings"] });
      toast.success(`Mel tool approval: ${r.mel_tool_approval.replace(/_/g, " ")}`);
    },
    onError: (e) => toast.error(String(e)),
  });

  const { data: auth } = useQuery({ queryKey: ["auth-status"], queryFn: api.authStatus, retry: false });
  const [currentPw, setCurrentPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const changePw = useMutation({
    mutationFn: () => api.changePassword(currentPw, newPw),
    onSuccess: () => {
      setCurrentPw("");
      setNewPw("");
      toast.success("Password changed");
    },
    onError: () => toast.error("Couldn't change password — check your current password."),
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
                  <a href={`${apiBaseUrl}/docs`} target="_blank" rel="noreferrer">
                    OpenAPI <ExternalLink className="h-3 w-3" />
                  </a>
                </Button>
                <Button variant="outline" size="sm" asChild>
                  <a href={`${apiBaseUrl}/health`} target="_blank" rel="noreferrer">
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

          {/* Login (change password) — only when in-app auth is enabled */}
          {auth?.auth_enabled && (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base flex items-center gap-2">
                  <KeyRound className="h-4 w-4" /> Login
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 text-sm">
                <Row label="Signed in as">
                  <Badge variant="secondary">{auth.username ?? "—"}</Badge>
                </Row>
                <div className="space-y-1.5">
                  <Label htmlFor="cur-pw">Current password</Label>
                  <Input
                    id="cur-pw"
                    type="password"
                    autoComplete="current-password"
                    value={currentPw}
                    onChange={(e) => setCurrentPw(e.target.value)}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="new-pw">New password</Label>
                  <Input
                    id="new-pw"
                    type="password"
                    autoComplete="new-password"
                    value={newPw}
                    onChange={(e) => setNewPw(e.target.value)}
                  />
                </div>
                <Button
                  size="sm"
                  onClick={() => changePw.mutate()}
                  disabled={!currentPw || !newPw || changePw.isPending}
                >
                  Change password
                </Button>
                <p className="text-xs text-muted-foreground pt-2 border-t">
                  Single shared login, gated by <code className="font-mono">AUTH_ENABLED</code>. The
                  password is hashed (scrypt) and stored encrypted at rest.
                </p>
              </CardContent>
            </Card>
          )}

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


          {/* Mel / trust */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2">
                <Bot className="h-4 w-4" /> Mel
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <div className="space-y-1.5">
                <Label>Tool approval</Label>
                <Select
                  value={data.mel_tool_approval ?? "run_sql_only"}
                  onValueChange={(v) => saveMelApproval.mutate(v as MelToolApprovalMode)}
                  disabled={saveMelApproval.isPending}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="run_sql_only">Approve run_sql (default)</SelectItem>
                    <SelectItem value="always">Approve every Mel tool</SelectItem>
                    <SelectItem value="auto">Auto-run (no prompts)</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <p className="text-xs text-muted-foreground pt-2 border-t">
                Mel&apos;s live DB tools stay <strong>read-only</strong>. By default,{" "}
                <code className="font-mono">run_sql</code> pauses for Approve/Deny in chat;
                list/describe can auto-run. Credentials and the Anthropic key stay on this
                machine (encrypted at rest) — Mel never ships them to third parties beyond the
                model API calls you configure.
              </p>
              <Button variant="outline" size="sm" asChild>
                <a href="/runs">View Mel tool audit on Runs</a>
              </Button>
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

          {/* Authentication (env-driven, read-only) */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2">
                <KeyRound className="h-4 w-4" /> Authentication
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              <Row label="In-app login">
                {data.auth_enabled ? (
                  <Badge variant="success">
                    <CheckCircle2 className="h-3 w-3 mr-1" /> enabled
                  </Badge>
                ) : (
                  <Badge variant="secondary">
                    <XCircle className="h-3 w-3 mr-1" /> disabled
                  </Badge>
                )}
              </Row>
              <Row label="Username">
                <code className="font-mono">{data.auth_username ?? "—"}</code>
              </Row>
              <Row label="Token TTL">
                <Badge variant="outline">{data.auth_token_ttl_hours}h</Badge>
              </Row>
              <p className="text-xs text-muted-foreground pt-2 border-t">
                Driven by <code className="font-mono">AUTH_ENABLED</code>,{" "}
                <code className="font-mono">AUTH_USERNAME</code>, and{" "}
                <code className="font-mono">AUTH_TOKEN_TTL_HOURS</code> in{" "}
                <code className="font-mono">.env</code>.{" "}
                <code className="font-mono">AUTH_PASSWORD</code> only seeds the credential on first
                login — change it above. Leave disabled when running behind oauth2-proxy/Keycloak.
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
