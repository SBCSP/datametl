import { NextRequest, NextResponse } from "next/server";

// Runtime same-origin proxy for the production deploy.
//
// Why this exists (and not next.config.ts rewrites): rewrites in next.config.ts are
// evaluated at *build* time and baked into routes-manifest.json. The published image
// has no NEXT_INTERNAL_API_BASE_URL set at build time, so build-time rewrites resolve
// to an empty list and the standalone server can't proxy anything.
//
// Middleware runs on every request, so it can read process.env at runtime — exactly
// what we need. When NEXT_INTERNAL_API_BASE_URL is set (deploy compose pins it to the
// backend container), requests to /api/* and a few API-adjacent paths get rewritten to
// hit the backend; the browser only ever sees same-origin /api/foo.
//
// In dev (next.js running with --reload, NEXT_INTERNAL_API_BASE_URL unset) this
// middleware no-ops and the existing NEXT_PUBLIC_API_BASE_URL CORS-cross-origin path
// handles things.

const PROXY_PREFIXES = ["/api/"];
const PROXY_EXACT = new Set(["/health", "/docs", "/openapi.json"]);

export function middleware(req: NextRequest) {
  const target = process.env.NEXT_INTERNAL_API_BASE_URL;
  if (!target) return NextResponse.next();

  const { pathname, search } = req.nextUrl;
  const shouldProxy =
    PROXY_EXACT.has(pathname) ||
    PROXY_PREFIXES.some((p) => pathname.startsWith(p)) ||
    pathname.startsWith("/docs/");

  if (!shouldProxy) return NextResponse.next();

  const dest = new URL(target);
  dest.pathname = pathname;
  dest.search = search;
  return NextResponse.rewrite(dest);
}

// Restrict middleware execution to paths that might match — saves work on every page
// load. The runtime check above is still authoritative.
export const config = {
  matcher: ["/api/:path*", "/health", "/docs/:path*", "/docs", "/openapi.json"],
};
