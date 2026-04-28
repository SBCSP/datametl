"use client";

import * as React from "react";
import { Moon, Sun, Monitor } from "lucide-react";
import { useTheme } from "next-themes";
import { cn } from "@/lib/utils";

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = React.useState(false);
  React.useEffect(() => setMounted(true), []);

  // Avoid hydration mismatch
  if (!mounted) return <div className="h-7 w-[84px]" />;

  const options: { value: "light" | "dark" | "system"; icon: React.ComponentType<{ className?: string }> }[] = [
    { value: "light", icon: Sun },
    { value: "system", icon: Monitor },
    { value: "dark", icon: Moon },
  ];

  return (
    <div className="inline-flex items-center rounded-md border bg-background p-0.5">
      {options.map((o) => {
        const Icon = o.icon;
        const active = theme === o.value;
        return (
          <button
            key={o.value}
            type="button"
            aria-label={`${o.value} theme`}
            onClick={() => setTheme(o.value)}
            className={cn(
              "flex h-6 w-7 items-center justify-center rounded transition-colors",
              active ? "bg-accent text-accent-foreground" : "text-muted-foreground hover:text-foreground",
            )}
          >
            <Icon className="h-3.5 w-3.5" />
          </button>
        );
      })}
    </div>
  );
}
