/**
 * Public viewer stand-in. The full app's version of this file talks to the
 * owner's server; the viewer has no server, so this one does nothing and
 * the original code is not part of the public build.
 */

export type BasemapConfig = {
  /** Always null here: the viewer uses the keyless OpenFreeMap basemap. */
  cartoApiKey: string | null;
  loaded: boolean;
};

export const BASEMAP_CONFIG_SOFT_TIMEOUT_MS = 3000;
export const BASEMAP_CONFIG_HARD_TIMEOUT_MS = 15000;

const KEYLESS: BasemapConfig = { cartoApiKey: null, loaded: true };

export function __resetBasemapConfigCache(): void {}

export function useBasemapConfig(): BasemapConfig {
  return KEYLESS;
}
