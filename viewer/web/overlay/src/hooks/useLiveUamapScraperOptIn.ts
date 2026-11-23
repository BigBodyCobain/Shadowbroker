/**
 * Public viewer stand-in. The full app's version of this file talks to the
 * owner's server; the viewer has no server, so this one does nothing and
 * the original code is not part of the public build.
 */

export type LiveUamapScraperStatus = {
  platform_requires_opt_in: boolean;
  ui_opted_in: boolean;
  scraper_enabled: boolean;
  env_override: 'on' | 'off' | null;
  ui_choice_recorded?: boolean;
  api_configured?: boolean;
  enrichment_enabled?: boolean;
  provider_mode?: 'api' | 'scraper' | 'gdelt-only';
};

export function useLiveUamapScraperOptIn(_enabled = true) {
  return {
    status: null as LiveUamapScraperStatus | null,
    refreshStatus: async () => {},
    needsConsentBeforeEnable: (_layerId: string, _turningOn: boolean) => false,
    confirmOptIn: async () => {},
  };
}
