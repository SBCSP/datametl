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

// Toned-down treatment: a subtle outline badge (faint colored border + muted colored text, no
// heavy fill) paired with a small solid dot that carries the at-a-glance color cue. The tile
// accent is a thin, low-opacity left border. Production leans slightly stronger as a safety nudge.
const STYLES: Record<Environment, EnvStyle> = {
  development: {
    label: "Development",
    badge: "gap-1.5 border-emerald-500/30 text-emerald-600 dark:text-emerald-400/90",
    border: "border-l-emerald-500/60",
    dot: "bg-emerald-500",
  },
  staging: {
    label: "Staging",
    badge: "gap-1.5 border-amber-500/30 text-amber-600 dark:text-amber-400/90",
    border: "border-l-amber-500/60",
    dot: "bg-amber-500",
  },
  production: {
    label: "Production",
    badge: "gap-1.5 border-red-500/40 text-red-600 dark:text-red-400",
    border: "border-l-red-500/80",
    dot: "bg-red-500",
  },
};

/** Returns the style for a known environment, or null when unset/unknown. */
export function envStyle(env: string | null | undefined): EnvStyle | null {
  if (env && env in STYLES) return STYLES[env as Environment];
  return null;
}
