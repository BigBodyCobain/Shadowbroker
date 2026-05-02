import { hasLocalControlBridge } from '@/lib/localControlTransport';
import {
  GATE_ACTIVITY_REFRESH_JITTER_MS,
  GATE_ACTIVITY_REFRESH_MS,
  GATE_MESSAGES_POLL_JITTER_MS,
  GATE_MESSAGES_POLL_MS,
} from '@/components/MeshChat/types';
import { jitterDelay } from '@/components/MeshChat/utils';

const GATE_BACKGROUND_MESSAGES_POLL_MS = 60_000;
const GATE_BACKGROUND_MESSAGES_POLL_JITTER_MS = 12_000;
const GATE_BACKGROUND_ACTIVITY_REFRESH_MS = 18_000;
const GATE_BACKGROUND_ACTIVITY_REFRESH_JITTER_MS = 4_000;
const GATE_MESSAGES_WAIT_MS = 32_000;
const GATE_MESSAGES_WAIT_JITTER_MS = 6_000;
const GATE_BACKGROUND_MESSAGES_WAIT_MS = 72_000;
const GATE_BACKGROUND_MESSAGES_WAIT_JITTER_MS = 12_000;
const GATE_MESSAGES_WAIT_REARM_MS = 3_600;
const GATE_MESSAGES_WAIT_REARM_JITTER_MS = 600;
const GATE_BACKGROUND_MESSAGES_WAIT_REARM_MS = 9_000;
const GATE_BACKGROUND_MESSAGES_WAIT_REARM_JITTER_MS = 3_000;

export function shouldJitterGateMetadataTiming(): boolean {
  return !hasLocalControlBridge();
}

function shouldCoarsenBackgroundGateTiming(): boolean {
  return (
    shouldJitterGateMetadataTiming() &&
    typeof document !== 'undefined' &&
    document.visibilityState === 'hidden'
  );
}

export function nextGateMessagesPollDelayMs(): number {
  if (!shouldJitterGateMetadataTiming()) {
    return GATE_MESSAGES_POLL_MS;
  }
  if (shouldCoarsenBackgroundGateTiming()) {
    return jitterDelay(
      GATE_BACKGROUND_MESSAGES_POLL_MS,
      GATE_BACKGROUND_MESSAGES_POLL_JITTER_MS,
    );
  }
  return jitterDelay(GATE_MESSAGES_POLL_MS, GATE_MESSAGES_POLL_JITTER_MS);
}

export function nextGateActivityRefreshDelayMs(): number {
  if (!shouldJitterGateMetadataTiming()) {
    return 0;
  }
  if (shouldCoarsenBackgroundGateTiming()) {
    return jitterDelay(
      GATE_BACKGROUND_ACTIVITY_REFRESH_MS,
      GATE_BACKGROUND_ACTIVITY_REFRESH_JITTER_MS,
    );
  }
  return jitterDelay(GATE_ACTIVITY_REFRESH_MS, GATE_ACTIVITY_REFRESH_JITTER_MS);
}

export function nextGateMessagesWaitTimeoutMs(): number {
  if (!shouldJitterGateMetadataTiming()) {
    return 20_000;
  }
  if (shouldCoarsenBackgroundGateTiming()) {
    return jitterDelay(
      GATE_BACKGROUND_MESSAGES_WAIT_MS,
      GATE_BACKGROUND_MESSAGES_WAIT_JITTER_MS,
    );
  }
  return jitterDelay(GATE_MESSAGES_WAIT_MS, GATE_MESSAGES_WAIT_JITTER_MS);
}

export function nextGateMessagesWaitRearmDelayMs(): number {
  if (!shouldJitterGateMetadataTiming()) {
    return 750;
  }
  if (shouldCoarsenBackgroundGateTiming()) {
    return jitterDelay(
      GATE_BACKGROUND_MESSAGES_WAIT_REARM_MS,
      GATE_BACKGROUND_MESSAGES_WAIT_REARM_JITTER_MS,
    );
  }
  return jitterDelay(GATE_MESSAGES_WAIT_REARM_MS, GATE_MESSAGES_WAIT_REARM_JITTER_MS);
}
