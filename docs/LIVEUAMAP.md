# LiveUAMap enrichment

Shadowbroker's **Global Incidents** layer does not depend on LiveUAMap. GDELT
remains the baseline incident source; LiveUAMap adds optional map-pin enrichment
when one of the providers below is available.

## Provider order

1. **Supported LiveUAMap API (optional)** — preferred when an operator has a
   paid/contracted API endpoint. Shadowbroker does not require this service.
2. **Browser provider (best effort)** — the existing Playwright integration.
   This remains enabled by default on Linux/macOS/Docker when Global Incidents
   is active, preserving existing behavior. Windows asks once before allowing
   the backend to contact LiveUAMap through the browser provider.
3. **GDELT-only** — if neither LiveUAMap provider is usable, Global Incidents
   still turns on and continues to receive GDELT data.

A LiveUAMap provider failure must never disable the broader Global Incidents
feature.

## Supported API configuration

Because LiveUAMap API endpoint/auth details are supplied under the operator's
service agreement, Shadowbroker does not hard-code a vendor account endpoint.
Configure the HTTPS JSON/GeoJSON URL you were given:

```env
LIVEUAMAP_API_URL=https://your-liveuamap-api-endpoint.example/events
LIVEUAMAP_API_KEY=your-key
LIVEUAMAP_API_AUTH_HEADER=Authorization
LIVEUAMAP_API_AUTH_SCHEME=Bearer
LIVEUAMAP_API_TIMEOUT_S=30
```

`LIVEUAMAP_API_KEY` is optional at the code level so deployments whose endpoint
already contains/handles authentication can still use the provider. The API URL
must use HTTPS. Keys are sent only in the configured request header and are not
included in provider-status responses or logs.

If the API request fails, Linux/macOS/Docker may fall back to the browser
provider under the existing browser-provider policy. Windows falls back only if
the operator separately opted into browser contact.

## Browser-provider behavior

The browser provider is **best effort** because it consumes an undocumented web
page representation rather than a stable public schema. Shadowbroker therefore:

- treats strings, wrapped objects, keyed objects, double-encoded JSON, legacy
  base64 payloads, and GeoJSON as bounded parser inputs;
- validates point coordinates before emitting markers;
- skips malformed entries instead of failing an entire region;
- detects obvious access/challenge pages and fails soft;
- pauses repeated browser attempts after consecutive complete failures;
- logs only structural payload diagnostics, not raw upstream payloads; and
- retains the existing browser/stealth profile without adding new anti-bot
  bypass techniques.

### Docker browser location (#516)

Published backend images install Playwright browsers into the shared
`/ms-playwright` directory through `PLAYWRIGHT_BROWSERS_PATH`. The image build
then verifies, as the non-root runtime user, that both Chromium and the matching
headless-shell bundle are present and executable. This prevents the previous
root-cache/runtime-user mismatch where the browser existed under `/root` while
Playwright searched under `/app/.cache`.

## Operator controls

```env
# Explicitly enable or disable only the browser provider.
SHADOWBROKER_ENABLE_LIVEUAMAP_SCRAPER=true
SHADOWBROKER_ENABLE_LIVEUAMAP_SCRAPER=false
```

On Windows, the first Global Incidents enable offers LiveUAMap browser
enrichment. **Accepting or declining never blocks Global Incidents itself.** A
decline is remembered so the UI does not nag on every toggle. The environment
flag remains the explicit override.

On Linux/macOS/Docker, leaving the flag unset preserves the historical behavior:
the browser provider may run while Global Incidents is active. Set it to
`false` if the operator wants GDELT-only operation unless a supported API is
configured.

## Failure semantics

LiveUAMap data is enrichment. If Chromium is missing, the upstream schema drifts,
the site presents an access challenge, the paid API is unavailable, or every
region returns malformed data, the provider returns no new pins and the error is
contained. GDELT fetching and the rest of the Shadowbroker data pipeline continue
independently.
