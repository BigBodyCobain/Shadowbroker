import React from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { ClassificationBadge, ConfidenceMeter } from '@/components/investigation/primitives';
import type { Confidence } from '@/types/investigation';

afterEach(cleanup);

function conf(partial: Partial<Confidence> = {}): Confidence {
  return {
    score: 0.72,
    percent: 72,
    label: 'high',
    qualitative: false,
    method: 'log_odds_v1',
    supporting: [{ label: 'aircraft anomaly', weight: 0.7 }],
    contradicting: [{ label: 'no official confirmation', weight: 0.4 }],
    rationale: '1 supporting vs 1 contradicting',
    ...partial,
  };
}

describe('ClassificationBadge', () => {
  it('labels a raw observation as a fact', () => {
    render(<ClassificationBadge value="raw_observation" />);
    expect(screen.getByText('FACT')).toBeTruthy();
  });

  it('labels a hypothesis as an inference (distinct from facts)', () => {
    render(<ClassificationBadge value="hypothesis" />);
    const badge = screen.getByText('HYPOTHESIS');
    expect(badge).toBeTruthy();
    // hypothesis title communicates it is not a confirmed fact
    expect(badge.getAttribute('title') || '').toMatch(/not confirmed fact/i);
  });
});

describe('ConfidenceMeter', () => {
  it('shows a numeric percentage when confidence is quantitative', () => {
    render(<ConfidenceMeter confidence={conf()} />);
    expect(screen.getByText('72%')).toBeTruthy();
  });

  it('shows a qualitative chip and no fake percentage when qualitative', () => {
    render(
      <ConfidenceMeter
        confidence={conf({ qualitative: true, score: null, percent: null, label: 'moderate' })}
      />,
    );
    expect(screen.getByText(/Qualitative: moderate/i)).toBeTruthy();
    expect(screen.queryByText('72%')).toBeNull();
  });

  it('reveals supporting and contradicting factors on expand', () => {
    render(<ConfidenceMeter confidence={conf()} />);
    fireEvent.click(screen.getByText(/Show supporting/i));
    expect(screen.getByText('aircraft anomaly')).toBeTruthy();
    expect(screen.getByText('no official confirmation')).toBeTruthy();
  });
});
