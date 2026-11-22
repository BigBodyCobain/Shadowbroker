# PR #2 — Hardening & Refactor Summary

Branch: `chore/consolidate-kill-scripts-deny-logs`
PR: https://github.com/esmaeelE/Shadowbroker/pull/2
Status: pushed and in sync with origin at `442a35d`

## Scope

This branch keeps the frontend green while removing type-check debt, hardening
operator auth and outbound fetches, and repairing runtime failures introduced
by the large mechanical component/hook extractions.

## What changed

### Frontend
- Removed every `// @ts-nocheck` from non-test source (0 remaining in `frontend/src` outside `__tests__`).
- Split `MaplibreViewer`, `MeshChat`, `MeshTerminal`, `SettingsPanel` and related
  popups into focused hooks/components; repaired the extracted prop bags where
  mechanical extraction dropped values (`Report`, `streamEnabledForSelectedGateRef`,
  `useMeshSendHandlers` / `useDeadDropAccess` / `useInfoNetPolling` ctx props).
- Fixed real UI bugs found during verification:
  - `MissionPanel` watch-load `Promise.all` destructuring.
  - `MessagesView` raw DM lookup regex (`{16 }` -> `{16,}`).
  - Risk badges no longer render `LVL: undefined/10` or `LVL: 0/10`; unknown
    scores show `INTEL` / `ALERT` or hide the badge.
  - Clipboard writes go through a helper that never rejects when the document
    is not focused.
  - Esri World Imagery sources are skipped when the host cannot be reached,
    avoiding one console error per tile.
- `MaplibreViewer`, `SettingsPanel` and hooks: reconstructed from caller
  contracts / git history where the extracted files had become unreadable.

### Backend / security
- `POST /api/sigint/transmit`, wormhole join/leave, Sentinel tile (main copy),
  mesh oracle resolve/resolve-stakes (main copy) and infonet swarm join now
  require explicit operator/admin auth.
- Route auth inventory (`scripts/route_auth_inventory.py`) upgraded to recognise
  in-handler HMAC/scoped/session checks, multi-line `Depends(...)`, signed-write
  helpers, peer gossip, and reviewed public endpoints. Result: **553 routes, 0 UNCLASSIFIED**.
- SSRF hardening:
  - Feed ingester uses DNS-pinned `safe_get`.
  - Mesh peer URLs (swarm, prekey, router, DM relay, main sync/push/pull) go
    through a proxy-aware peer guard that allows legitimate loopback/RFC1918
    peers while blocking credentials, metadata hosts, link-local/reserved IPs
    and IPv6 ULA.
  - CCTV APRR liveness validates the host; frame freshness kept on the original
    `requests.get` after a DNS-pinned variant broke mocked upstreams.
- Madrid CCTV KML fetch prefers HTTPS with an HTTP fallback.
- OSM tile proxy retries transient upstream failures (3 attempts, backoff).
- Repeated MLS key-package export tracebacks are logged once per alias.
- Signed-write v1 protocol vectors added at `docs/protocol/signed-write-v1-vectors.json`.

### Test stabilisation
- Updated stale source-shape tests for moved helpers (task timeout drain,
  lifespan node-state wiring, signed-write exemption, alias-rotation reason
  constant) and updater mocks for the current 6-tuple release metadata.
- Injection-entrypoint tests pass a real `Request`.
- Added `backend/tests/test_ssrf_peer_guard.py`.

## Verification

### Frontend
| Check | Result |
|---|---|
| `npx tsc --noEmit` | pass |
| `npm run build` | pass |
| `npm run test:ci` | **129 files / 1131 tests passed** |

### Backend (clean worktree, `-p no:randomly`)
| Run | Failed | Passed | Skipped |
|---|---|---|---|
| `main` baseline | 335 | 2911 | 16 |
| this branch | **315** | **2936** | 16 |

- **0 new failures** vs `main`
- **20 baseline failures fixed**

### Runtime smoke
With both servers running, all checked endpoints returned 200 through the Next
proxy: `/`, `/api/health`, `/api/layers`, `/api/bootstrap/critical`,
`/api/settings/wormhole`, `/api/mesh/infonet/status`, `/api/osm-tile/...`.
Protected endpoints return 403 until `ADMIN_KEY` from `frontend/.env.local` is
entered in **Settings → Admin key**.

## Remaining failures

The remaining 315 backend failures are unchanged from `main` and are
environmental: missing privacy-core native library (`PrivacyCoreUnavailable`),
missing `MESH_SECURE_STORAGE_SECRET`, absent/invalid external API credentials
(OpenSky), and live-network-dependent feed tests. They require a properly
provisioned environment to resolve.

## Running locally

```bash
# preferred: prebuilt images
docker compose pull && docker compose up -d
# open http://localhost:3000

# from source (two terminals)
cd backend && ../.venv/bin/python main.py
cd frontend && npm run dev:frontend
```

Operator key: `frontend/.env.local` / `backend/.env` contain a matching
`ADMIN_KEY`; paste it into **Settings → Admin key** to clear the expected 403s.
