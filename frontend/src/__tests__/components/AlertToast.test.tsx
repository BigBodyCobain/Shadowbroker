import React from 'react';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import AlertToast from '@/components/AlertToast';
import type { ToastItem } from '@/hooks/useAlertToasts';

function buildToast(partial: Partial<ToastItem> = {}): ToastItem {
  return {
    id: 'toast-1',
    title: 'Embassy evacuation reported',
    source: 'Reuters',
    risk_score: 9,
    lat: 38.9,
    lng: -77.0,
    timestamp: Date.now(),
    ...partial,
  };
}

describe('AlertToast', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it('renders the toast title, source, and severity label', () => {
    const toast = buildToast();
    render(
      <AlertToast toasts={[toast]} onDismiss={vi.fn()} />,
    );

    expect(screen.getByText(toast.title)).toBeTruthy();
    expect(screen.getByText(toast.source)).toBeTruthy();
    // 9/10 -> CRITICAL
    expect(screen.getByText(/CRITICAL/)).toBeTruthy();
    expect(screen.getByText(/LVL 9\/10/)).toBeTruthy();
  });

  it('auto-dismisses after 5 seconds', () => {
    const onDismiss = vi.fn();
    const toast = buildToast();
    render(
      <AlertToast toasts={[toast]} onDismiss={onDismiss} />,
    );

    expect(onDismiss).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(5000);
    });

    expect(onDismiss).toHaveBeenCalledWith(toast.id);
  });

  it('pauses auto-dismiss while the card is hovered', () => {
    const onDismiss = vi.fn();
    const toast = buildToast();
    render(
      <AlertToast toasts={[toast]} onDismiss={onDismiss} />,
    );

    // Hover before the timer fires. mouseEnter must be flushed
    // (state update + effect cleanup) in its own act() before we
    // advance timers — otherwise the original mount-time timer is
    // still active when advanceTimersByTime runs.
    const card = screen.getByText(toast.title).closest('[class*="cursor-pointer"]')!;
    expect(card).toBeTruthy();

    act(() => {
      fireEvent.mouseEnter(card);
    });
    act(() => {
      vi.advanceTimersByTime(10_000);
    });

    // Still no dismiss — timer is paused.
    expect(onDismiss).not.toHaveBeenCalled();

    // Leave: a fresh full-lifetime timer starts.
    act(() => {
      fireEvent.mouseLeave(card);
    });
    act(() => {
      vi.advanceTimersByTime(4_999);
    });
    expect(onDismiss).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(onDismiss).toHaveBeenCalledWith(toast.id);
  });

  it('dismisses on × button click without calling onFlyTo', () => {
    const onDismiss = vi.fn();
    const onFlyTo = vi.fn();
    const toast = buildToast();
    render(
      <AlertToast toasts={[toast]} onDismiss={onDismiss} onFlyTo={onFlyTo} />,
    );

    fireEvent.click(screen.getByText('×'));

    expect(onDismiss).toHaveBeenCalledWith(toast.id);
    expect(onFlyTo).not.toHaveBeenCalled();
  });

  it('flies to the toast location and dismisses on body click', () => {
    const onDismiss = vi.fn();
    const onFlyTo = vi.fn();
    const toast = buildToast();
    render(
      <AlertToast toasts={[toast]} onDismiss={onDismiss} onFlyTo={onFlyTo} />,
    );

    fireEvent.click(screen.getByText(toast.title));

    expect(onFlyTo).toHaveBeenCalledWith(toast.lat, toast.lng);
    expect(onDismiss).toHaveBeenCalledWith(toast.id);
  });
});
