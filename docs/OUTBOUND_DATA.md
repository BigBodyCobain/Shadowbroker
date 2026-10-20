# Outbound data and third-party exposure

Shadowbroker is **self-hosted**: each install uses its own backend egress IP. This document is the operator-facing record for GitHub audit issues **#348–#366** (tg12): what contacts third parties, why, and how to opt out without losing unrelated features.

## Architecture

| Path | Who calls third parties |
|------|-------------------------|
| Map UI → `/api/*` → fetchers | **This install’s backend** |
| Basemap tiles / fonts | **Operator’s browser** (CARTO, demotiles.maplibre.org) |
| CCTV still/video proxy | **Backend** (Referer/Origin set per agency — see #349) |

---

## Issue disposition summary

| Issue | Status | Approach |
|-------|--------|----------|
| **#351** | Fixed | Region dossier via backend proxy |
| **#352** | Fixed | Geocode via `/api/geocode` only |
| **#360** | Fixed | Wikipedia/Wikidata via backend |
| **#362** | Fixed | `DEEPSTATE_MIRROR_COMMIT` optional pin |
| **#363** | Fixed | Madrid KML HTTPS-first |
| **#364** | Fixed | KiwiSDR HTTPS-first + validation |
| **#348** | Accepted + gated | Windows UI opt-in; env override; stealth documented |
| **#349** | Accepted + documented | Agency-required Referer on backend proxy only |
| **#350** | Mitigated | Callsign in UA **off by default**; opt-in `MESHTASTIC_SEND_CALLSIGN_HEADER=true` |
| **#354** | Accepted + documented | Default basemap CDN; optional self-hosted tiles |
| **#361** | Mitigated | UA is **install handle only** (`operator-…`), not shared `Shadowbroker/` token |
| **#366** | Accepted + documented | Honest per-install scrape; feature degrades if blocked |

---

## Per-install User-Agent (#361)

- **Code:** `backend/services/network_utils.py` — `outbound_user_agent()`, `OPERATOR_HANDLE`
- **Sent:** `operator-7f3a92` or `your-handle (purpose: nominatim)` — **no** shared app product name
- **Why:** Upstreams can rate-limit **one install**; a block on `operator-abc123` does not require blocking every Shadowbroker user
- **Override:** `SHADOWBROKER_USER_AGENT` replaces the entire string
- **Note:** The same handle across Wikipedia, Broadcastify, etc. still correlates **your** traffic across those sites — that is intentional per-install attribution, not anonymity

---

## LiveUAMap scraper (#348)

- **Layer:** `global_incidents` (LiveUAMap map pins; **GDELT** text still loads without LiveUAMap)
- **Code:** `backend/services/liveuamap_scraper.py` (Playwright + stealth for Turnstile)
- **Windows:** Scraper **off** until you enable **Global Incidents** and confirm the UI dialog → `backend/data/liveuamap_scraper_opt_in.json`
- **Linux/macOS:** Scraper runs when the layer is on (unless env forces off)
- **API:** `GET /api/liveuamap/scraper-status`, `POST /api/liveuamap/scraper-opt-in`
- **Env:** `SHADOWBROKER_ENABLE_LIVEUAMAP_SCRAPER=true|false` overrides UI on all platforms
- **Honesty:** Backend-only; no browser-direct LiveUAMap from end users. Stealth remains a functional tradeoff for Turnstile; disable layer or env if unacceptable

## UAP sightings (NUFORC map layer)

- **Window:** last **60 days** (`NUFORC_RECENT_DAYS`, ~2 months) from **live** nuforc.org
- **Cadence:** **Weekly** (Monday 12:00 UTC) per install; typical yield **~400–500** geocoded pins
- **Between weeks:** `backend/data/nuforc_recent_sightings.json` (7-day TTL) so restarts do not wipe the layer
- **Immediate pull:** admin `GET /api/refresh` on that install
- **Not used for map pins:** stale Hugging Face mirror (frozen ~2023) unless live is down and mirror happens to have in-window rows

---

## CCTV proxy Referer / Origin (#349)

- **Code:** `backend/routers/cctv.py`, `backend/main.py`
- **Behavior:** Backend proxies streams and sets `Referer` / `Origin` each agency expects (e.g. `https://511ga.org/cctv`, `https://informo.madrid.es/`)
- **Exposure:** Agency sees **backend IP**, not each viewer’s browser
- **Not removed:** Without these headers, most public DOT/city feeds return 403 — this is not end-user browser impersonation, it is the same headers a normal browser session would send to play the feed

---

## Meshtastic map callsign (#350)

- **Layer:** `sigint_meshtastic` must be active for `fetch_meshtastic_nodes()`
- **Default:** `MESHTASTIC_SEND_CALLSIGN_HEADER=false` — callsign **not** sent to `meshtastic.liamcottle.net` unless you set `true`
- **Optional:** `MESHTASTIC_OPERATOR_CALLSIGN` for local display; header only when explicitly enabled

---

## Basemap CDN (#354, #583)

- **Code:** `frontend/src/components/map/styles/mapStyles.ts`
- **Default host:** `tiles.openfreemap.org`
- **Default behavior:** OpenFreeMap Dark/Positron vector styles load without registration or an API key. OpenFreeMap's public instance is the zero-config path.
- **Optional CARTO override:** If `CARTO_API_KEY` is configured (env or API Keys panel), ShadowBroker keeps the existing CARTO raster dark/light basemap. The key is served by `GET /api/basemap-config` and sent by the browser to `*.basemaps.cartocdn.com`.
- **Exposure:** Basemap requests are made by the **browser**, so the selected provider sees browser network metadata and requested map resources.
- **Attribution:** ShadowBroker explicitly displays OpenStreetMap plus the active basemap provider attribution.
- **Self-hosting:** OpenFreeMap is open-source and supports self-hosting; operators can replace the public basemap endpoint if they need full infrastructure control.

---

## Broadcastify top feeds (#366)

- **Code:** `backend/services/radio_intercept.py`
- **Behavior:** Backend fetches `https://www.broadcastify.com/listen/top` with per-install handle UA; parses public HTML for feed metadata and CDN stream URLs
- **Exposure:** Your backend IP; 5-minute cache
- **If blocked:** Panel shows empty list — feature not removed from the app
- **Not:** Fake Chrome UA or cloudscraper bypass (removed in Round 7a)

---

## Ukraine frontline mirror (#362)

- **Layer:** `ukraine_frontline` / `frontlines`
- **Pin:** `DEEPSTATE_MIRROR_COMMIT`, optional `DEEPSTATE_MIRROR_REPO`

## Madrid CCTV (#363) / KiwiSDR (#364)

- Madrid: HTTPS-first KML catalog; image URLs unchanged
- KiwiSDR: HTTPS-first directory fetch; shape validation + bundled fallback

---

## Operator checklist

1. Set `OPERATOR_HANDLE` if you want a recognizable name on upstream logs.
2. Pin `DEEPSTATE_MIRROR_COMMIT` for reproducible frontlines (optional).
3. Windows: enable Global Incidents in UI only if you accept LiveUAMap server contact.
4. Set `SHADOWBROKER_ENABLE_LIVEUAMAP_SCRAPER=false` to forbid LiveUAMap entirely.
5. Set `MESHTASTIC_SEND_CALLSIGN_HEADER=true` only if you want callsign sent upstream.
6. Self-host map tiles if basemap CDN exposure matters.
