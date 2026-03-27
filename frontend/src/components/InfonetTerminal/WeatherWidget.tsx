'use client';

import React, { useState, useEffect } from 'react';

const LOCATIONS = [
  { name: 'Night City', tz: 'America/Los_Angeles', tempC: 18 },
  { name: 'Tokyo', tz: 'Asia/Tokyo', tempC: 22 },
  { name: 'New York', tz: 'America/New_York', tempC: 25 },
  { name: 'London', tz: 'Europe/London', tempC: 12 },
  { name: 'Neo Seoul', tz: 'Asia/Seoul', tempC: 19 },
];

export default function WeatherWidget() {
  const [locIdx, setLocIdx] = useState(0);
  const [isCelsius, setIsCelsius] = useState(false);
  const [time, setTime] = useState(new Date());

  useEffect(() => {
    const timer = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  const loc = LOCATIONS[locIdx];
  const temp = isCelsius ? loc.tempC : Math.round(loc.tempC * 9/5 + 32);
  const tempUnit = isCelsius ? 'C' : 'F';

  const timeString = time.toLocaleTimeString('en-US', { timeZone: loc.tz, hour12: false, hour: '2-digit', minute: '2-digit' });
  const dateString = time.toLocaleDateString('en-US', { timeZone: loc.tz, month: 'short', day: 'numeric' });

  return (
    <div className="flex items-center gap-2 text-sm md:text-xs text-gray-400 border border-gray-800 bg-gray-900/30 px-2 py-1 shrink-0 font-mono tracking-widest uppercase whitespace-nowrap">
      <span>{dateString} {timeString}</span>
      <span className="text-gray-700">|</span>
      <span
        className="cursor-pointer hover:text-white transition-colors"
        onClick={() => setLocIdx((i) => (i + 1) % LOCATIONS.length)}
        title="Change Location & Timezone"
      >
        {loc.name}
      </span>
      <span className="text-gray-700">|</span>
      <span
        className="cursor-pointer hover:text-white transition-colors"
        onClick={() => setIsCelsius(!isCelsius)}
        title="Toggle C / F"
      >
        {temp}&deg;{tempUnit}
      </span>
    </div>
  );
}
