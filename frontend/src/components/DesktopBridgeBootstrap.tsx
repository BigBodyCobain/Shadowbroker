'use client';

import { useEffect } from 'react';
import { bootstrapDesktopControlBridge } from '@/lib/desktopBridge';

export default function DesktopBridgeBootstrap() {
  useEffect(() => {
    bootstrapDesktopControlBridge();
  }, []);

  return null;
}
