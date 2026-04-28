import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,

  // `standalone` produces a self-contained .next/standalone output (just the runtime files
  // the production image needs) — used by the multi-stage Dockerfile's `prod` target.
  output: "standalone",

  // Note: production deployments proxy /api/* to the backend container via
  // `frontend/middleware.ts` (runtime; reads NEXT_INTERNAL_API_BASE_URL on every request).
  // We deliberately do NOT use next.config.ts rewrites here because async rewrites are
  // evaluated at build time and baked into routes-manifest.json — by which point our
  // env var isn't set, and the standalone server has no way to learn it later.
};

export default nextConfig;
