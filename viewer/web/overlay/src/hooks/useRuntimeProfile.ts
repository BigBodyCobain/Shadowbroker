/**
 * Public viewer stand-in. The full app's version of this file talks to the
 * owner's server; the viewer has no server, so this one does nothing and
 * the original code is not part of the public build.
 */

export interface RuntimeGtAnalytics {
  enabled?: boolean;
  operational?: boolean;
  profile?: string;
  lean_node?: boolean;
  recommended?: boolean;
  warning?: string | null;
  experimental?: boolean;
}

export interface RuntimeProfile {
  profile?: string;
  cpu_limit?: number | null;
  memory_limit_mb?: number | null;
  gt_analytics?: RuntimeGtAnalytics;
}

export function useRuntimeProfile(): RuntimeProfile | null {
  return null;
}

export function gtLeanLayerWarning(_runtime: RuntimeProfile | null): string | null {
  return null;
}
