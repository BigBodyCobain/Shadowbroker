// ─── ShadowBroker Frontend Constants ────────────────────────────────────────
// Centralized magic numbers. Import from here instead of hardcoding.

// ─── Data Polling ───────────────────────────────────────────────────────────
export const POLL_FAST_STARTUP_MS = 3000;
export const POLL_FAST_STEADY_MS = 15000;
export const POLL_SLOW_STARTUP_MS = 5000;
export const POLL_SLOW_STEADY_MS = 120000;

// ─── Reverse Geocoding ──────────────────────────────────────────────────────
export const GEOCODE_THROTTLE_MS = 2200;
export const GEOCODE_DISTANCE_THRESHOLD = 0.12; // ~13km in degrees
export const GEOCODE_CACHE_SIZE = 500;
export const NOMINATIM_DEBOUNCE_MS = 350;

// ─── Map Interpolation ─────────────────────────────────────────────────────
export const INTERP_TICK_MS = 2000;

// ─── News/Alert Layout ──────────────────────────────────────────────────────
export const ALERT_BOX_WIDTH_PX = 280;
export const ALERT_MAX_OFFSET_PX = 500;
