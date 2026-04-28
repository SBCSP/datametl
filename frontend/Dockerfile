# syntax=docker/dockerfile:1.7
# Multi-stage. The dev compose builds with `target: dev` (live reload, npm run dev). The
# release workflow builds with `target: prod` for the published GHCR image (Next.js
# standalone output, ~50MB final image, runs `node server.js`).

FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install


# --- dev: bind-mount source + npm run dev ---
FROM deps AS dev
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
EXPOSE 3000
CMD ["npm", "run", "dev"]


# --- builder: produces the production .next/standalone output ---
FROM deps AS builder
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
# NEXT_PUBLIC_API_BASE_URL is intentionally empty for the published image — the frontend
# uses Next.js rewrites (server-side) to proxy /api/* to the backend container, so the
# browser always fetches same-origin and never needs to know the backend's URL.
ENV NEXT_PUBLIC_API_BASE_URL=
RUN npm run build


# --- prod: tiny final image, just node + the standalone output ---
FROM node:20-alpine AS prod
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3000
ENV HOSTNAME=0.0.0.0
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public
EXPOSE 3000
CMD ["node", "server.js"]
