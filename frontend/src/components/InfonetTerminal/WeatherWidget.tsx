'use client';

import React, { useState, useEffect } from 'react';

export default function WeatherWidget() {
  const [time, setTime] = useState(new Date());

  useEffect(() => {
    const timer = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  const timeString = time.toLocaleTimeString('en-US', {
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
  });
  const dateString = time.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
  });

  return (
    <div className="flex items-center gap-2 text-sm md:text-xs text-gray-400 border border-gray-800 bg-gray-900/30 px-2 py-1 shrink-0 font-mono tracking-widest uppercase whitespace-nowrap">
      <span>{dateString} {timeString}</span>
    </div>
  );
}
