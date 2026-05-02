import React from 'react';

export function RepBadge({ rep }: { rep: number }) {
  const color =
    rep >= 50
      ? 'text-yellow-400'
      : rep >= 10
        ? 'text-cyan-400'
        : rep > 0
          ? 'text-cyan-600'
          : rep < 0
            ? 'text-red-400'
            : 'text-gray-600';
  return (
    <span className={`text-[13px] font-mono font-bold ${color} shrink-0`}>
      {rep >= 0 ? '+' : ''}
      {rep}
    </span>
  );
}
