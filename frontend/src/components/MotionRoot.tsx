'use client';

import { MotionProvider } from '@/lib/motion';

/** Client boundary so RootLayout can stay a Server Component. */
export default function MotionRoot({ children }: { children: React.ReactNode }) {
  return <MotionProvider>{children}</MotionProvider>;
}
