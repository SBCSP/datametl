"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Sidebar } from "@/components/sidebar";
import { McpBanner } from "@/components/mcp-banner";
import { OnboardingModal } from "@/components/onboarding-modal";
import { useActivityNotifications } from "@/lib/use-activity-notifications";

/** Decides whether to render the sidebar + padded main, or a bare canvas (for printable
 * report routes), and gates the app behind the simple in-app login when AUTH_ENABLED. */
export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const isLogin = pathname === "/login";
  const bare = pathname.endsWith("/report");
  // Full-bleed, full-height routes (chat) manage their own scroll and padding so they can use
  // the entire viewport instead of the centered, padded content container.
  const fullBleed = pathname === "/chat";

  // Auth gate. /api/auth/status is public; when auth is disabled it reports authenticated=true.
  const authStatus = useQuery({
    queryKey: ["auth-status"],
    queryFn: api.authStatus,
    retry: false,
    staleTime: 30_000,
  });
  const needsLogin = !!authStatus.data?.auth_enabled && !authStatus.data.authenticated;
  const checkOnboarding =
    !!authStatus.data?.auth_enabled &&
    !!authStatus.data.authenticated &&
    !needsLogin &&
    !isLogin;

  // Onboard gate: zero memberships → block UI even if cutover tenant is bound.
  const tenantsMe = useQuery({
    queryKey: ["tenants-me"],
    queryFn: api.tenantsMe,
    enabled: checkOnboarding,
    retry: false,
    staleTime: 15_000,
  });
  const needsOnboarding = checkOnboarding && tenantsMe.data?.needs_onboarding === true;

  useEffect(() => {
    if (needsLogin && !isLogin) router.replace("/login");
  }, [needsLogin, isLogin, router]);

  // Don't poll protected endpoints on the login screen / when unauthenticated / onboard.
  useActivityNotifications({ enabled: !needsLogin && !isLogin && !needsOnboarding });

  // The login page renders standalone (no sidebar).
  if (isLogin) {
    return <main>{children}</main>;
  }
  if (needsLogin) {
    return (
      <div className="flex min-h-dvh items-center justify-center text-sm text-muted-foreground">
        Redirecting to sign in…
      </div>
    );
  }

  if (checkOnboarding && tenantsMe.isLoading && tenantsMe.data === undefined) {
    return (
      <div className="flex min-h-dvh items-center justify-center text-sm text-muted-foreground">
        Loading workspace…
      </div>
    );
  }

  if (needsOnboarding) {
    return (
      <>
        <div className="pointer-events-none select-none opacity-40" aria-hidden>
          <Sidebar />
          <div className="md:pl-60">
            <main className="mx-auto max-w-7xl px-6 py-8" />
          </div>
        </div>
        <OnboardingModal />
      </>
    );
  }

  if (bare) {
    return <main className="mx-auto max-w-5xl px-6 py-8 print:max-w-none print:px-0">{children}</main>;
  }
  if (fullBleed) {
    return (
      <>
        <Sidebar />
        <div className="flex h-dvh flex-col md:pl-60">
          <McpBanner />
          <main className="min-h-0 flex-1">{children}</main>
        </div>
      </>
    );
  }
  return (
    <>
      <Sidebar />
      <div className="md:pl-60">
        <McpBanner />
        <main className="mx-auto max-w-7xl px-6 py-8">{children}</main>
      </div>
    </>
  );
}
