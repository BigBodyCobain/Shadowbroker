import type { NextConfig } from 'next';

// /api/* requests are proxied to the backend by the catch-all route handler at
// src/app/api/[...path]/route.ts, which reads BACKEND_URL at request time.
// Do NOT add rewrites for /api/* here — next.config is evaluated at build time,
// so any URL baked in here ignores the runtime BACKEND_URL env var.

const skipTypecheck = process.env.NEXT_SKIP_TYPECHECK === '1';

// Desktop packaging: set NEXT_OUTPUT=export to produce a static export
// (frontend/out/) suitable for Tauri bundling and companion server hosting.
// This disables API routes, middleware, and server-side image optimization —
// all handled by the Tauri shell and companion server in packaged mode.
// Default remains 'standalone' for the web deployment (Docker/Vercel).
const isDesktopExport = process.env.NEXT_OUTPUT === 'export';

// CSP is now emitted dynamically by src/middleware.ts (Phase 5F-A) so that
// each document response carries a unique per-request nonce.  Non-CSP
// security headers remain here because they are static and benefit from
// next.config's catch-all source matcher.
const securityHeaders = [
  {
    key: 'Referrer-Policy',
    value: 'no-referrer',
  },
  {
    key: 'X-Content-Type-Options',
    value: 'nosniff',
  },
  {
    key: 'X-Frame-Options',
    value: 'DENY',
  },
];

const nextConfig: NextConfig = {
  transpilePackages: ['react-map-gl', 'maplibre-gl'],
  output: isDesktopExport ? 'export' : 'standalone',
  devIndicators: false,
  experimental: isDesktopExport
    ? {
        webpackBuildWorker: false,
        parallelServerCompiles: false,
        parallelServerBuildTraces: false,
        workerThreads: false,
      }
    : undefined,
  images: {
    unoptimized: isDesktopExport,
    remotePatterns: [
      { protocol: 'https', hostname: 'upload.wikimedia.org' },
      { protocol: 'https', hostname: 'via.placeholder.com' },
      { protocol: 'https', hostname: 'services.sentinel-hub.com' },
      { protocol: 'https', hostname: 'data.sentinel-hub.com' },
      { protocol: 'https', hostname: 'sentinel-hub.com' },
      { protocol: 'https', hostname: 'dataspace.copernicus.eu' },
    ],
  },
  typescript: {
    ignoreBuildErrors: skipTypecheck,
  },
  ...(!isDesktopExport
    ? {
        async headers() {
          return [
            {
              source: '/:path*',
              headers: securityHeaders,
            },
          ];
        },
      }
    : {}),
};

export default nextConfig;
