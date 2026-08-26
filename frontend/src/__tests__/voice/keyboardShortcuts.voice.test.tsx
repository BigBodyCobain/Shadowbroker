/**
 * §7.D item 34 — keyboard V PTT extension: fires down/up only outside inputs,
 * e.repeat ignored, and undefined voicePtt keeps legacy behavior byte-identical.
 */
import React from 'react';
import { cleanup, fireEvent, render } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { useKeyboardShortcuts } from '@/hooks/useKeyboardShortcuts';

type Actions = Parameters<typeof useKeyboardShortcuts>[0];

function baseActions(overrides: Partial<Actions> = {}): Actions {
  return {
    toggleLeft: vi.fn(),
    toggleRight: vi.fn(),
    toggleMarkets: vi.fn(),
    openSettings: vi.fn(),
    openLegend: vi.fn(),
    openShortcuts: vi.fn(),
    deselectEntity: vi.fn(),
    focusSearch: vi.fn(),
    ...overrides,
  };
}

function Harness({ actions }: { actions: Actions }) {
  useKeyboardShortcuts(actions);
  return <div />;
}

describe('useKeyboardShortcuts voicePtt (V)', () => {
  afterEach(cleanup);

  it('V fires begin on keydown and end on keyup', () => {
    const begin = vi.fn();
    const end = vi.fn();
    render(<Harness actions={baseActions({ voicePtt: { begin, end } })} />);
    fireEvent.keyDown(document, { key: 'v' });
    expect(begin).toHaveBeenCalledTimes(1);
    fireEvent.keyUp(document, { key: 'v' });
    expect(end).toHaveBeenCalledTimes(1);
  });

  it('ignores V while typing in an input', () => {
    const begin = vi.fn();
    const end = vi.fn();
    render(<Harness actions={baseActions({ voicePtt: { begin, end } })} />);
    const input = document.createElement('input');
    document.body.appendChild(input);
    const down = new KeyboardEvent('keydown', { key: 'v', bubbles: true });
    Object.defineProperty(down, 'target', { value: input });
    document.dispatchEvent(down);
    const up = new KeyboardEvent('keyup', { key: 'v', bubbles: true });
    Object.defineProperty(up, 'target', { value: input });
    document.dispatchEvent(up);
    expect(begin).not.toHaveBeenCalled();
    expect(end).not.toHaveBeenCalled();
    input.remove();
  });

  it('ignores e.repeat holds', () => {
    const begin = vi.fn();
    render(<Harness actions={baseActions({ voicePtt: { begin, end: vi.fn() } })} />);
    const repeatEvent = new KeyboardEvent('keydown', { key: 'v', bubbles: true });
    Object.defineProperty(repeatEvent, 'repeat', { value: true });
    document.dispatchEvent(repeatEvent);
    expect(begin).not.toHaveBeenCalled();
  });

  it('window blur force-releases the hold', () => {
    const end = vi.fn();
    render(<Harness actions={baseActions({ voicePtt: { begin: vi.fn(), end } })} />);
    window.dispatchEvent(new Event('blur'));
    expect(end).toHaveBeenCalled();
  });

  it('undefined voicePtt leaves legacy behavior byte-identical (V unbound)', () => {
    const toggleLeft = vi.fn();
    render(<Harness actions={baseActions({ toggleLeft })} />);
    // No crash, no listener errors; L still works.
    fireEvent.keyDown(document, { key: 'l' });
    expect(toggleLeft).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(document, { key: 'v' });
    expect(toggleLeft).toHaveBeenCalledTimes(1);
    fireEvent.keyUp(document, { key: 'v' });
    expect(toggleLeft).toHaveBeenCalledTimes(1);
  });

  it('Ctrl fires begin on keydown and end on keyup', () => {
    const begin = vi.fn();
    const end = vi.fn();
    render(<Harness actions={baseActions({ voicePtt: { begin, end } })} />);
    fireEvent.keyDown(document, { key: 'Control' });
    expect(begin).toHaveBeenCalledTimes(1);
    fireEvent.keyUp(document, { key: 'Control' });
    expect(end).toHaveBeenCalledTimes(1);
  });

  it('Ctrl works while focused in an input (produces no characters)', () => {
    const begin = vi.fn();
    const end = vi.fn();
    render(<Harness actions={baseActions({ voicePtt: { begin, end } })} />);
    const input = document.createElement('input');
    document.body.appendChild(input);
    const down = new KeyboardEvent('keydown', { key: 'Control', bubbles: true });
    Object.defineProperty(down, 'target', { value: input });
    document.dispatchEvent(down);
    expect(begin).toHaveBeenCalledTimes(1);
    const up = new KeyboardEvent('keyup', { key: 'Control', bubbles: true });
    Object.defineProperty(up, 'target', { value: input });
    document.dispatchEvent(up);
    expect(end).toHaveBeenCalledTimes(1);
    input.remove();
  });

  it('a combo while Ctrl is held cancels the hold without transmitting', () => {
    const begin = vi.fn();
    const end = vi.fn();
    render(<Harness actions={baseActions({ voicePtt: { begin, end } })} />);
    fireEvent.keyDown(document, { key: 'Control' });
    expect(begin).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(document, { key: 'c', ctrlKey: true });
    expect(end).toHaveBeenCalledTimes(1);
  });
});
