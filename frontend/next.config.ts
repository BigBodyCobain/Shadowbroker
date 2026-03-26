import type { NextConfig } from "next";

// /api/* requests are proxied to the backend by the catch-all route handler at
// src/app/api/[...path]/route.ts, which reads BACKEND_URL at request time.
// Do NOT add rewrites for /api/* here — next.config is evaluated at build time,
// so any URL baked in here ignores the runtime BACKEND_URL env var.

const nextConfig: NextConfig = {
  transpilePackages: ['react-map-gl', 'mapbox-gl', 'maplibre-gl'],
  // "standalone" is needed for Docker (copies only required files).
  // Vercel manages its own output, so skip it there.
  output: process.env.DOCKER_BUILD ? "standalone" : undefined,
};

export default nextConfig;
