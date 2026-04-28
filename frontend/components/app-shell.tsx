"use client";

import { usePathname } from "next/navigation";
import { Sidebar } from "@/components/sidebar";
import { useActivityNotifications } from "@/lib/use-activity-notifications";

/** Decides whether to render the sidebar + padded main, or a bare canvas (for printable
 * report routes that should look clean when shared / printed to PDF). Also mounts the
 * global activity-notifications hook so toasts fire on any page. */
export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const bare = pathname.endsWith("/report");

  // Even on the print-friendly report page we want notifications — but toasts are hidden
  // by the existing `print:hidden` toaster styles, so it's harmless.
  useActivityNotifications();

  if (bare) {
    return <main className="mx-auto max-w-5xl px-6 py-8 print:max-w-none print:px-0">{children}</main>;
  }
  return (
    <>
      <Sidebar />
      <div className="md:pl-60">
        <main className="mx-auto max-w-7xl px-6 py-8">{children}</main>
      </div>
    </>
  );
}
