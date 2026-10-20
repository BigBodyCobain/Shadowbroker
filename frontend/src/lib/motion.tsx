'use client';

/**
 * Shared framer-motion entry — LazyMotion + domAnimation keeps the animation
 * feature set small instead of pulling the full motion bundle into every panel.
 *
 * Import `motion` / `AnimatePresence` from here (not `framer-motion`) so the
 * app stays on the lightweight `m` component under LazyMotion.
 */
import type { ReactNode } from 'react';
import {
  LazyMotion,
  domAnimation,
  m,
  AnimatePresence,
} from 'framer-motion';

export { LazyMotion, domAnimation, AnimatePresence };
export const motion = m;

export function MotionProvider({ children }: { children: ReactNode }) {
  return (
    <LazyMotion features={domAnimation} strict>
      {children}
    </LazyMotion>
  );
}
