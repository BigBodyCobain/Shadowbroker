import type { NextConfig } from 'next';

// Public viewer build: a plain static site. No server, no API routes, no proxy.
// Set when the site is published in a sub-folder of another site, e.g. "/map".
const basePath = process.env.NEXT_PUBLIC_SB_BASE_PATH || '';

const nextConfig: NextConfig = {
  ...(basePath ? { basePath } : {}),
  transpilePackages: ['react-map-gl'],
  output: 'export',
  devIndicators: false,
  images: { unoptimized: true },
  typescript: { tsconfigPath: 'tsconfig.build.json' },
  experimental: {
    webpackBuildWorker: false,
    parallelServerCompiles: false,
    parallelServerBuildTraces: false,
    workerThreads: false,
  },
};

export default nextConfig;
