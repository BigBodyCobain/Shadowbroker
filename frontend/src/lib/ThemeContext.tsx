'use client';

import React, { createContext, useContext, useState, useEffect } from 'react';

type Theme = 'dark' | 'light';
type HudColor = 'cyan' | 'matrix';
/** Sensor view: recolours the basemap (and tints satellite imagery) like an optic mode. */
export type SensorMode = 'off' | 'flir' | 'nvg' | 'crt';
export const SENSOR_MODES: SensorMode[] = ['off', 'flir', 'nvg', 'crt'];

const ThemeContext = createContext<{
  theme: Theme;
  toggleTheme: () => void;
  setTheme: (t: Theme) => void;
  hudColor: HudColor;
  cycleHudColor: () => void;
  setHudColor: (h: HudColor) => void;
  sensor: SensorMode;
  setSensor: (s: SensorMode) => void;
}>({
  theme: 'dark',
  toggleTheme: () => {},
  setTheme: () => {},
  hudColor: 'cyan',
  cycleHudColor: () => {},
  setHudColor: () => {},
  sensor: 'off',
  setSensor: () => {},
});

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = useState<Theme>('dark');
  const [hudColor, setHudColorState] = useState<HudColor>('cyan');
  const [sensor, setSensorState] = useState<SensorMode>('off');

  useEffect(() => {
    const saved = localStorage.getItem('sb-theme') as Theme | null;
    if (saved === 'light' || saved === 'dark') {
      setThemeState(saved);
      document.documentElement.setAttribute('data-theme', saved);
    }
    const savedHud = localStorage.getItem('sb-hud-color') as HudColor | null;
    if (savedHud === 'cyan' || savedHud === 'matrix') {
      setHudColorState(savedHud);
      document.documentElement.setAttribute('data-hud', savedHud);
    }
    const savedSensor = localStorage.getItem('sb-sensor') as SensorMode | null;
    if (savedSensor && SENSOR_MODES.includes(savedSensor)) {
      setSensorState(savedSensor);
      document.documentElement.setAttribute('data-sensor', savedSensor);
    } else {
      document.documentElement.setAttribute('data-sensor', 'off');
    }
  }, []);

  const setTheme = (next: Theme) => {
    setThemeState(next);
    localStorage.setItem('sb-theme', next);
    document.documentElement.setAttribute('data-theme', next);
  };

  const setHudColor = (next: HudColor) => {
    setHudColorState(next);
    localStorage.setItem('sb-hud-color', next);
    document.documentElement.setAttribute('data-hud', next);
  };

  const setSensor = (next: SensorMode) => {
    setSensorState(next);
    localStorage.setItem('sb-sensor', next);
    document.documentElement.setAttribute('data-sensor', next);
  };

  const toggleTheme = () => setTheme(theme === 'dark' ? 'light' : 'dark');

  const cycleHudColor = () => setHudColor(hudColor === 'cyan' ? 'matrix' : 'cyan');

  return (
    <ThemeContext.Provider
      value={{ theme, toggleTheme, setTheme, hudColor, cycleHudColor, setHudColor, sensor, setSensor }}
    >
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  return useContext(ThemeContext);
}
