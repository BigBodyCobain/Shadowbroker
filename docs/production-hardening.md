# Production hardening checklist

Use this before merging PRs that touch the **data path**, **fetchers**, **live-data APIs**, or anything that runs **unattended for more than an hour** (Docker, VPS self-host).

Adapt as needed — not every item applies to UI-only or docs-only PRs.

## Config and exposure

- [ ] Do new or changed config flags default to the **safe** value (loopback bind, features off until opt-in)?
- [ ] Is any wider exposure (LAN bind, clearnet upstreams, admin without key) gated behind an **explicit env opt-in**?

## Live-data API

- [ ] When an endpoint's payload shape or sources change, does its serializer match siblings (`default=str`, `OPT_NON_STR_KEYS` via `_live_data_json_bytes` in `routers/data.py`)?
- [ ] Is each route path defined **exactly once**? Grep the path — duplicate `main.py` + router copies drift.
- [ ] Do ETag prefixes distinguish response variants (full vs fast vs slow, initial vs full, bbox suffix)?

## Fetcher pools and timeouts

- [ ] Do `future.result(timeout=...)` sites cancel queued work on timeout (or document why running threads are idempotent)?
- [ ] Do `*_CONCURRENCY` knobs agree with the executor pool size they run on?
- [ ] Does retry/backoff match intent — transient network/5xx retried; **HTTP 4xx from `raise_for_status` not retried** (`services/fetchers/retry.py`)?
- [ ] Are outbound HTTP calls timeout-bounded (`timeout=` on `requests.*`, explicit timeout on `fetch_with_curl`, Playwright `set_default_*_timeout`)?

## Secrets and observability

- [ ] Are secrets read from env only, never logged by value; missing keys logged by **variable name**?
- [ ] Do `record_success` / `record_failure` reflect what actually happened?

## Tests

- [ ] Do regression tests assert **properties** (serialization survives non-JSON-native values, slow pool cannot starve fast tier under load), not only wiring (which executor a label uses)?

## Spot-checked heavy paths (2026-06)

| Path | Timeout posture |
|------|-----------------|
| `services/geopolitics.py` (GDELT) | `fetch_with_curl(..., timeout=10/15)` per export file |
| `services/fetchers/flights.py` | `requests` / `fetch_with_curl` with 10–30s |
| `services/fetchers/earth_observation.py` | `fetch_with_curl` / `session.get|post` with explicit timeouts |
| `services/liveuamap_scraper.py` | `page.goto(..., timeout=60s)` + context default timeouts |

Re-audit when adding a new fetcher or changing scheduler cadence.

## Related issues

- [#375](https://github.com/BigBodyCobain/Shadowbroker/issues/375) — dev bind, store lock, slow executor
- [#239](https://github.com/BigBodyCobain/Shadowbroker/issues/239) — duplicate route CI guard (`test_no_new_duplicate_routes.py`)
