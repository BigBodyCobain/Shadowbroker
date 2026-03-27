import type { NextConfig } from 'next';

// /api/* requests are proxied to the backend by the catch-all route handler at
// src/app/api/[...path]/route.ts, which reads BACKEND_URL at request time.
// Do NOT add rewrites for /api/* here — next.config is evaluated at build time,
// so any URL baked in here ignores the runtime BACKEND_URL env var.

const skipTypecheck = process.env.NEXT_SKIP_TYPECHECK === '1';
const isDev = process.env.NODE_ENV !== 'production';
const securityHeaders = [
  {
    key: 'Content-Security-Policy',
    value: [
      "default-src 'self'",
      isDev
        ? "script-src 'self' 'unsafe-inline' 'unsafe-eval' blob:"
        : "script-src 'self' 'unsafe-inline' blob:",
      "style-src 'self' 'unsafe-inline'",
      "img-src 'self' data: blob: https:",
      isDev
        ? "connect-src 'self' ws: wss: http://127.0.0.1:8000 http://127.0.0.1:8787 https:"
        : "connect-src 'self' ws: wss: https:",
      "font-src 'self' data:",
      "object-src 'none'",
      "worker-src 'self' blob:",
      "child-src 'self' blob:",
      "frame-ancestors 'none'",
      "base-uri 'self'",
      "form-action 'self'",
    ].join('; '),
  },
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
  output: 'standalone',
  devIndicators: false,
  images: {
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
  async headers() {
    return [
      {
        source: '/:path*',
        headers: securityHeaders,
      },
    ];
  },
};

export default nextConfig;
