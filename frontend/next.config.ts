import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,

  // `standalone` produces a self-contained .next/standalone output (just the runtime files
  // the production image needs) — used by the multi-stage Dockerfile's `prod` target.
  // Harmless in dev (only affects `next build` output).
  output: "standalone",

  // In production deployments the frontend container proxies `/api/*` to the backend
  // container by service name. The browser only ever sees the frontend's origin, so:
  //   * no CORS dance — same-origin requests
  //   * no need to bake the backend host:port into the JS bundle
  //   * users can remap host ports freely without rebuilding
  //
  // In dev, NEXT_INTERNAL_API_BASE_URL is unset and rewrites are skipped — the dev
  // frontend uses NEXT_PUBLIC_API_BASE_URL (cross-origin to the backend container's host
  // port) and the backend has CORS configured to match.
  async rewrites() {
    const target = process.env.NEXT_INTERNAL_API_BASE_URL;
    if (!target) return [];
    return [
      { source: "/api/:path*", destination: `${target}/api/:path*` },
      { source: "/health", destination: `${target}/health` },
      { source: "/docs", destination: `${target}/docs` },
      { source: "/openapi.json", destination: `${target}/openapi.json` },
    ];
  },
};

export default nextConfig;
