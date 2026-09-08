"use client";

import Link from "next/link";
import {
  Bot,
  KeyRound,
  Lock,
  Server,
  ShieldCheck,
  EyeOff,
  FileSearch,
  BadgeCheck,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/page-header";

/** Verified from backend/app/mcp/tools.py — keep in sync if TOOL_ROW_CAP changes. */
const TOOL_ROW_CAP = 200;

export default function TrustPage() {
  return (
    <div>
      <PageHeader
        title="Trust & security"
        description="Where your credentials and Mel data go — matching what DataMETL does today."
        breadcrumbs={[
          { label: "Settings", href: "/settings" },
          { label: "Trust" },
        ]}
        actions={
          <Button variant="outline" size="sm" asChild>
            <Link href="/settings">Open Settings</Link>
          </Button>
        }
      />

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <Lock className="h-4 w-4" /> Credentials stay local
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm text-muted-foreground">
            <p>
              Connection passwords and optional SSL CA PEMs stay on{" "}
              <strong className="text-foreground">your machine</strong> and the{" "}
              <strong className="text-foreground">Docker network you run</strong>. They are{" "}
              <strong className="text-foreground">never</strong> sent to SandboxCSP or a vendor cloud.
            </p>
            <p>
              At rest they are encrypted with <strong className="text-foreground">Fernet</strong>{" "}
              (<code className="font-mono text-xs text-foreground">ENCRYPTION_KEY</code>). The API
              never returns passwords or PEMs — only redacted connection metadata.
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <Bot className="h-4 w-4" /> Mel → Anthropic
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm text-muted-foreground">
            <p>
              Mel uses <strong className="text-foreground">your</strong> Anthropic API key (also
              Fernet-encrypted at rest).
            </p>
            <p className="text-foreground font-medium text-xs uppercase tracking-wide pt-1">
              Sent to the model
            </p>
            <ul className="list-disc pl-5 space-y-1">
              <li>Chat prompts and Mel system instructions</li>
              <li>
                Tool results: schema / describe metadata and query row samples, capped at{" "}
                <Badge variant="secondary" className="align-middle">
                  {TOOL_ROW_CAP} rows
                </Badge>{" "}
                (<code className="font-mono text-xs">TOOL_ROW_CAP</code>)
              </li>
            </ul>
            <p className="text-foreground font-medium text-xs uppercase tracking-wide pt-2 flex items-center gap-1">
              <EyeOff className="h-3.5 w-3.5" /> Not sent to the LLM
            </p>
            <ul className="list-disc pl-5 space-y-1">
              <li>Database passwords or connection secrets</li>
              <li>Fernet encryption key, Stripe secrets, or license signing keys</li>
            </ul>
            <p className="pt-1">
              Credentials are decrypted only inside your backend to run tools locally; capped JSON
              results go back to the model.
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <FileSearch className="h-4 w-4" /> Read-only MCP + approve-to-run
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm text-muted-foreground">
            <p>
              Live tools (<code className="font-mono text-xs text-foreground">list_tables</code>,{" "}
              <code className="font-mono text-xs text-foreground">describe_table</code>,{" "}
              <code className="font-mono text-xs text-foreground">run_sql</code>) always run{" "}
              <strong className="text-foreground">read-only</strong> — writes/DDL are rejected.
            </p>
            <ul className="list-disc pl-5 space-y-1">
              <li>
                <code className="font-mono text-xs text-foreground">run_sql_only</code> — approve SQL
                (Pro default)
              </li>
              <li>
                <code className="font-mono text-xs text-foreground">always</code> — approve every Mel
                DB tool (Community is forced here)
              </li>
              <li>
                <code className="font-mono text-xs text-foreground">auto</code> — no prompts (still
                read-only; Pro)
              </li>
            </ul>
            <p>
              Mel tool use is audited (redacted args, decision, outcome). See{" "}
              <Link href="/runs" className="underline text-foreground">
                Runs
              </Link>{" "}
              or configure modes in{" "}
              <Link href="/settings" className="underline text-foreground">
                Settings → Mel
              </Link>
              .
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <BadgeCheck className="h-4 w-4" /> Licensing
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm text-muted-foreground">
            <p>
              Self-hosted Pro keys are <strong className="text-foreground">offline-verified</strong>{" "}
              with <strong className="text-foreground">Ed25519</strong> (<code className="font-mono text-xs text-foreground">dmtl1.…</code>).
              No phone-home to SandboxCSP for normal activation.
            </p>
            <p>
              <strong className="text-foreground">Stripe secrets</strong> live only on a vendor{" "}
              <strong className="text-foreground">issuer</strong> (Phase 2 webhook). Your Community /
              Pro install only pastes a signed key — Stripe is optional and not required on the
              operator machine.
            </p>
            <p className="text-xs">
              Team is an entitlement stub; in-app multi-user SSO/RBAC is not shipped. Edge SSO via
              oauth2-proxy/Keycloak (Helm) is separate.
            </p>
          </CardContent>
        </Card>

        <Card className="md:col-span-2">
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <ShieldCheck className="h-4 w-4" /> Community vs Pro
            </CardTitle>
          </CardHeader>
          <CardContent className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-muted-foreground">
                  <th className="py-2 pr-4 font-medium">Capability</th>
                  <th className="py-2 pr-4 font-medium">Community</th>
                  <th className="py-2 font-medium">Pro</th>
                </tr>
              </thead>
              <tbody className="text-muted-foreground">
                <tr className="border-b">
                  <td className="py-2 pr-4 text-foreground">Postgres migrate / introspect / compare / verify</td>
                  <td className="py-2 pr-4">Yes</td>
                  <td className="py-2">Yes</td>
                </tr>
                <tr className="border-b">
                  <td className="py-2 pr-4 text-foreground">Mel chat</td>
                  <td className="py-2 pr-4">Yes</td>
                  <td className="py-2">Yes</td>
                </tr>
                <tr className="border-b">
                  <td className="py-2 pr-4 text-foreground">Mel tool approval modes</td>
                  <td className="py-2 pr-4">
                    Forced <code className="font-mono text-xs">always</code>
                  </td>
                  <td className="py-2">
                    <code className="font-mono text-xs">run_sql_only</code> /{" "}
                    <code className="font-mono text-xs">always</code> /{" "}
                    <code className="font-mono text-xs">auto</code>
                  </td>
                </tr>
                <tr className="border-b">
                  <td className="py-2 pr-4 text-foreground">MySQL + SQL Server connectors</td>
                  <td className="py-2 pr-4">No</td>
                  <td className="py-2">Yes</td>
                </tr>
                <tr>
                  <td className="py-2 pr-4 text-foreground">Stripe on your install</td>
                  <td className="py-2 pr-4">Not required</td>
                  <td className="py-2">Not required</td>
                </tr>
              </tbody>
            </table>
          </CardContent>
        </Card>

        <Card className="md:col-span-2">
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <Server className="h-4 w-4" /> Honest limits
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm text-muted-foreground">
            <ul className="list-disc pl-5 space-y-1">
              <li>
                When Mel tools run, <strong className="text-foreground">row samples</strong> can leave
                your network to Anthropic (capped at {TOOL_ROW_CAP}). Credentials do not.
              </li>
              <li>
                We do not claim built-in multi-user accounts or viewer/operator RBAC as shipped
                product features.
              </li>
              <li>
                Default Buy Pro Payment Link may be Stripe <strong className="text-foreground">test</strong>{" "}
                mode until a live URL is configured.
              </li>
            </ul>
            <div className="flex flex-wrap gap-2 pt-2">
              <Button variant="outline" size="sm" asChild>
                <Link href="/settings">
                  <KeyRound className="h-3.5 w-3.5 mr-1" /> Settings & license
                </Link>
              </Button>
              <Button variant="outline" size="sm" asChild>
                <Link href="/chat">Open Mel</Link>
              </Button>
            </div>
            <p className="text-xs pt-2 border-t">
              Full write-up for operators and websites:{" "}
              <code className="font-mono">docs/TRUST.md</code> in the DataMETL repo.
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
