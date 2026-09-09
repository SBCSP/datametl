"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Activity, Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import { setToken } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

function consumeOAuthHash(): boolean {
  if (typeof window === "undefined") return false;
  const raw = window.location.hash.replace(/^#/, "");
  if (!raw || !raw.includes("token=")) return false;
  const params = new URLSearchParams(raw);
  const token = params.get("token");
  if (!token) return false;
  setToken(token);
  // Drop the fragment so a refresh does not re-apply a stale token URL.
  window.history.replaceState(null, "", window.location.pathname + window.location.search);
  window.location.href = "/";
  return true;
}

export default function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [oauthLanding, setOauthLanding] = useState(false);

  useEffect(() => {
    if (consumeOAuthHash()) setOauthLanding(true);
  }, []);

  const { data: status, isLoading: statusLoading } = useQuery({
    queryKey: ["auth-status"],
    queryFn: api.authStatus,
    retry: false,
  });

  const githubOn = Boolean(status?.github_oauth_enabled);
  // Default true when the field is absent (older backends) so basic login still shows.
  const legacyOn = status?.legacy_basic_enabled !== false;

  const login = useMutation({
    mutationFn: () => api.login(username.trim(), password),
    onSuccess: (r) => {
      setToken(r.token);
      // Full reload so the whole app re-initializes authenticated.
      window.location.href = "/";
    },
    onError: () => setError("Invalid username or password."),
  });

  if (oauthLanding) {
    return (
      <div className="flex min-h-dvh items-center justify-center px-4">
        <p className="text-sm text-muted-foreground flex items-center gap-2">
          <Loader2 className="h-4 w-4 animate-spin" />
          Finishing GitHub sign-in…
        </p>
      </div>
    );
  }

  return (
    <div className="flex min-h-dvh items-center justify-center px-4">
      <Card className="w-full max-w-sm">
        <CardHeader className="space-y-2 text-center">
          <div className="mx-auto flex h-11 w-11 items-center justify-center rounded-md bg-primary text-primary-foreground">
            <Activity className="h-5 w-5" />
          </div>
          <CardTitle className="text-xl">Sign in to DataMETL</CardTitle>
          <CardDescription>
            {githubOn && !legacyOn
              ? "Continue with GitHub to access your workspace."
              : "Enter your credentials to continue."}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {githubOn && (
            <Button
              type="button"
              variant={legacyOn ? "outline" : "default"}
              className="w-full"
              disabled={statusLoading}
              onClick={() => {
                window.location.href = "/api/auth/github/start";
              }}
            >
              Continue with GitHub
            </Button>
          )}

          {githubOn && legacyOn && (
            <div className="relative py-1">
              <div className="absolute inset-0 flex items-center">
                <span className="w-full border-t" />
              </div>
              <div className="relative flex justify-center text-xs uppercase">
                <span className="bg-card px-2 text-muted-foreground">or</span>
              </div>
            </div>
          )}

          {legacyOn && (
            <form
              className="space-y-4"
              onSubmit={(e) => {
                e.preventDefault();
                setError(null);
                if (username.trim() && password) login.mutate();
              }}
            >
              <div className="space-y-1.5">
                <Label htmlFor="username">Username</Label>
                <Input
                  id="username"
                  autoFocus={!githubOn}
                  autoComplete="username"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="password">Password</Label>
                <Input
                  id="password"
                  type="password"
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              </div>
              {error && <p className="text-sm text-destructive">{error}</p>}
              <Button type="submit" className="w-full" disabled={!username.trim() || !password || login.isPending}>
                {login.isPending && <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />}
                Sign in
              </Button>
            </form>
          )}

          {!statusLoading && !githubOn && !legacyOn && (
            <p className="text-sm text-muted-foreground text-center">
              No sign-in methods are enabled on this server.
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
