/**
 * "Leaving disconnects InfoNet" notice.
 *
 * Closing InfoNet tears down Tor and the Wormhole on purpose (nothing private
 * keeps running in the background). This asks before that happens so it is
 * not a surprise, unless the user chose "don't show again".
 */
import { isInfonetSessionActive } from '@/lib/infonetTerminalSession';

const SUPPRESS_KEY = 'sb_infonet_leave_notice_suppressed_v1';

type PendingLeave = { proceed: () => void } | null;
type Listener = (pending: PendingLeave) => void;

let pending: PendingLeave = null;
const listeners = new Set<Listener>();

function emit() {
  for (const listener of listeners) listener(pending);
}

export function isInfonetLeaveNoticeSuppressed(): boolean {
  try {
    return localStorage.getItem(SUPPRESS_KEY) === '1';
  } catch {
    return false;
  }
}

export function setInfonetLeaveNoticeSuppressed(suppressed: boolean): void {
  try {
    if (suppressed) localStorage.setItem(SUPPRESS_KEY, '1');
    else localStorage.removeItem(SUPPRESS_KEY);
  } catch {
    /* storage unavailable: the notice keeps showing */
  }
}

/**
 * Run `leave` now if nothing is connected or the notice is suppressed;
 * otherwise ask first and run it only if the user confirms.
 */
export function requestInfonetLeave(leave: () => void): void {
  if (!isInfonetSessionActive() || isInfonetLeaveNoticeSuppressed()) {
    leave();
    return;
  }
  pending = { proceed: leave };
  emit();
}

export function resolveInfonetLeave(confirmed: boolean, dontShowAgain = false): void {
  const current = pending;
  pending = null;
  emit();
  if (!current || !confirmed) return;
  if (dontShowAgain) setInfonetLeaveNoticeSuppressed(true);
  current.proceed();
}

export function subscribeInfonetLeave(listener: Listener): () => void {
  listeners.add(listener);
  listener(pending);
  return () => {
    listeners.delete(listener);
  };
}
