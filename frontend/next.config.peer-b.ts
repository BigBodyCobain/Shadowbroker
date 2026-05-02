import baseConfig from './next.config';
import type { NextConfig } from 'next';

const peerConfig: NextConfig = {
  ...baseConfig,
  distDir: '.next-peer-b',
};

export default peerConfig;
