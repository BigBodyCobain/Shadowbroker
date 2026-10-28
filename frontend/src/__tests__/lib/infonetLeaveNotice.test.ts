import { beforeEach, describe, expect, it, vi } from 'vitest';

let active = false;
vi.mock('@/lib/infonetTerminalSession', () => ({
  isInfonetSessionActive: () => active,
}));

import {
  isInfonetLeaveNoticeSuppressed,
  requestInfonetLeave,
  resolveInfonetLeave,
  setInfonetLeaveNoticeSuppressed,
  subscribeInfonetLeave,
} from '@/lib/infonetLeaveNotice';

describe('infonetLeaveNotice', () => {
  beforeEach(() => {
    active = false;
    setInfonetLeaveNoticeSuppressed(false);
    resolveInfonetLeave(false);
  });

  it('leaves immediately when no session is connected', () => {
    const leave = vi.fn();
    requestInfonetLeave(leave);
    expect(leave).toHaveBeenCalledTimes(1);
  });

  it('asks first while connected, and only leaves on confirm', () => {
    active = true;
    const seen: boolean[] = [];
    const unsubscribe = subscribeInfonetLeave((pending) => seen.push(Boolean(pending)));
    const leave = vi.fn();

    requestInfonetLeave(leave);
    expect(leave).not.toHaveBeenCalled();
    expect(seen.at(-1)).toBe(true);

    resolveInfonetLeave(false);
    expect(leave).not.toHaveBeenCalled();
    expect(seen.at(-1)).toBe(false);

    requestInfonetLeave(leave);
    resolveInfonetLeave(true);
    expect(leave).toHaveBeenCalledTimes(1);
    unsubscribe();
  });

  it('"don\'t show again" skips the notice from then on', () => {
    active = true;
    const first = vi.fn();
    requestInfonetLeave(first);
    resolveInfonetLeave(true, true);
    expect(first).toHaveBeenCalledTimes(1);
    expect(isInfonetLeaveNoticeSuppressed()).toBe(true);

    const second = vi.fn();
    requestInfonetLeave(second);
    expect(second).toHaveBeenCalledTimes(1);
  });
});
