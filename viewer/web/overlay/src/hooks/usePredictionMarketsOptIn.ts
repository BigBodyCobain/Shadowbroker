/**
 * Public viewer stand-in. The full app's version of this file talks to the
 * owner's server; the viewer has no server, so this one does nothing and
 * the original code is not part of the public build.
 */

export type PredictionMarketsStatus = {
  enabled: boolean;
  ui_opted_in: boolean;
  env_override: 'on' | 'off' | null;
  jitter?: {
    scheduler_interval_minutes: number;
    scheduler_jitter_seconds: number;
    pre_fetch_jitter_seconds: number;
  };
};

const OFF: PredictionMarketsStatus = { enabled: false, ui_opted_in: false, env_override: 'off' };

export function usePredictionMarketsOptIn(_enabled = true) {
  return {
    status: OFF as PredictionMarketsStatus | null,
    refreshStatus: async () => {},
    setOptIn: async (_optedIn: boolean) => OFF,
  };
}
