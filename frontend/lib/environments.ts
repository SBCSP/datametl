// Environment labels for connections. Drives the colored tiles on the Connections and Schemas
// pages: development = green, staging = amber, production = red.

export type Environment = "development" | "staging" | "production";

export const ENVIRONMENTS: { value: Environment; label: string }[] = [
  { value: "development", label: "Development" },
  { value: "staging", label: "Staging" },
  { value: "production", label: "Production" },
];

export interface EnvStyle {
  label: string;
  /** Badge classes (background + text). */
  badge: string;
  /** Left-border accent class for tiles/cards. */
  border: string;
  /** Solid dot color. */
  dot: string;
}

const STYLES: Record<Environment, EnvStyle> = {
  development: {
    label: "Development",
    badge: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400 border-transparent",
    border: "border-l-emerald-500",
    dot: "bg-emerald-500",
  },
  staging: {
    label: "Staging",
    badge: "bg-amber-500/15 text-amber-700 dark:text-amber-400 border-transparent",
    border: "border-l-amber-500",
    dot: "bg-amber-500",
  },
  production: {
    label: "Production",
    badge: "bg-red-500/15 text-red-700 dark:text-red-400 border-transparent",
    border: "border-l-red-500",
    dot: "bg-red-500",
  },
};

/** Returns the style for a known environment, or null when unset/unknown. */
export function envStyle(env: string | null | undefined): EnvStyle | null {
  if (env && env in STYLES) return STYLES[env as Environment];
  return null;
}
