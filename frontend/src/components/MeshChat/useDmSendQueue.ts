'use client';

import { useCallback, useRef } from 'react';
import { shouldQueueDmSend } from '@/lib/meshChatPolicies';

export function useDmSendQueue(privacyProfile: string) {
  const dmSendQueue = useRef<(() => Promise<void>)[]>([]);
  const dmSendTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const flushDmQueue = useCallback(async () => {
    const queue = dmSendQueue.current.splice(0);
    if (dmSendTimer.current) {
      clearTimeout(dmSendTimer.current);
      dmSendTimer.current = null;
    }
    for (const task of queue) {
      try {
        await task();
      } catch {
        /* ignore */
      }
    }
  }, []);

  const enqueueDmSend = useCallback(
    (task: () => Promise<void>) => {
      return new Promise<void>((resolve) => {
        const wrapped = async () => {
          try {
            await task();
          } catch {
            /* ignore */
          } finally {
            resolve();
          }
        };
        if (!shouldQueueDmSend(privacyProfile)) {
          void wrapped();
          return;
        }
        dmSendQueue.current.push(wrapped);
        if (!dmSendTimer.current) {
          const delay = 120 + Math.random() * 180;
          dmSendTimer.current = setTimeout(() => {
            void flushDmQueue();
          }, delay);
        }
      });
    },
    [privacyProfile, flushDmQueue],
  );

  return { flushDmQueue, enqueueDmSend };
}
