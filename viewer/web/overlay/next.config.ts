import type { NextConfig } from 'next';

// Public viewer build: a plain static site. No server, no API routes, no proxy.
const nextConfig: NextConfig = {
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
