/**
 * AisUpstreamBanner — visible notice that AISStream ship data is unavailable.
 *
 * Renders nothing when AIS is healthy or when AIS isn't configured at all.
 * When AISStream is silent, nudge operators toward the existing AISHub REST
 * backup (Settings → API Keys) or confirm that backup is already active.
 */
import { useState } from 'react';
import { useAisUpstreamHealth } from '@/hooks/useAisUpstreamHealth';

type AisUpstreamBannerProps = {
  onOpenApiKeys?: () => void;
};

export function AisUpstreamBanner({ onOpenApiKeys }: AisUpstreamBannerProps = {}) {
  const health = useAisUpstreamHealth();
  const [dismissed, setDismissed] = useState(false);

  if (!health || !health.aisEnabled || health.connected || dismissed) {
    return null;
  }

  // Format the staleness for the operator. ``null`` means we never received
  // anything since startup; otherwise show minutes if > 60s.
  let stalenessLabel = 'never received';
  if (health.lastMsgAgeSeconds != null) {
    const minutes = Math.floor(health.lastMsgAgeSeconds / 60);
    if (minutes >= 1) {
      stalenessLabel = `last update ${minutes} min ago`;
    } else {
      stalenessLabel = `last update ${health.lastMsgAgeSeconds}s ago`;
    }
  }

  const detail = health.aishubConfigured
    ? `AISStream is silent (${stalenessLabel}). AISHub backup polling stays active on a slower cadence (~20 min) — live WebSocket traffic will resume when AISStream recovers.`
    : `AISStream is silent (${stalenessLabel}). Add a free AISHub username under Settings → API Keys → Maritime for slow backup ship coverage while AISStream is down.`;

  return (
    <div
      role="status"
      aria-live="polite"
      className="pointer-events-auto fixed top-3 left-1/2 z-[100] -translate-x-1/2 max-w-[640px] rounded-md border border-amber-500/60 bg-amber-900/85 px-4 py-2 text-sm text-amber-50 shadow-lg backdrop-blur"
    >
      <div className="flex items-start gap-3">
        <span aria-hidden className="mt-0.5 text-amber-300">⚠</span>
        <div className="flex-1">
          <div className="font-semibold">
            {health.aishubConfigured
              ? 'Live AIS offline — AISHub backup active'
              : 'Ship data temporarily unavailable'}
          </div>
          <div className="text-xs opacity-90">{detail}</div>
          {!health.aishubConfigured && onOpenApiKeys ? (
            <button
              type="button"
              onClick={onOpenApiKeys}
              className="mt-2 text-[11px] font-mono tracking-wide text-amber-100 underline underline-offset-2 hover:text-white"
            >
              Open API Keys
            </button>
          ) : null}
        </div>
        <button
          type="button"
          onClick={() => setDismissed(true)}
          aria-label="Dismiss"
          className="text-amber-200 hover:text-white"
        >
          ✕
        </button>
      </div>
    </div>
  );
}

export default AisUpstreamBanner;
