import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "./providers";
import { Toaster } from "sonner";
import { AppShell } from "@/components/app-shell";

export const metadata: Metadata = {
  title: "DataMETL",
  description: "Local-first data migration tool",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="min-h-screen bg-background text-foreground antialiased">
        <Providers>
          <AppShell>{children}</AppShell>
          <Toaster richColors position="top-right" />
        </Providers>
      </body>
    </html>
  );
}
