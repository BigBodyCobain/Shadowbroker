# ShadowBroker verification record — final local candidate

Date: 2026-08-23. Source baseline:
`fe44b052b08547aa57b030e45a3fc0fb2f946b87`; the candidate has uncommitted
changes. `NEXT_PUBLIC_PUBLIC_READ_ONLY=true` was used only for the local
browser/build candidate. No publication action was performed.

## Passed

- Targeted ESLint over every changed public-boundary, map, status and news-feed
  surface: `0` errors and `0` warnings.
- Targeted regression suite: `4` files / `34` tests passed, including Time
  Machine public-boundary, host detection, page decomposition and slow-health
  Strict Mode coverage.
- Full frontend suite: `94` files / `818` tests passed.
- `NEXT_PUBLIC_PUBLIC_READ_ONLY=true npm run build`: canonical public contracts
  regenerated from their inputs, TypeScript passed, and the production build
  completed.
- Local browser, production build, proxied to current public data at
  `127.0.0.1:3017`: compact `390x844` and desktop `1440x960` evidence both
  show one H1, no public operator/system/market/AI controls, the explicit Time
  Machine boundary, and a truthful `Data service degraded` state. Browser
  console: `0` errors, `0` warnings; CSP report-only messages are informational.
- Final browser request inventory has no Time Machine, SAR, AI-pin, prediction,
  or viewport-sync request. Health remains a permitted public request and
  returned `200`.
- Direct local-candidate probes of `/api/sar/aois`, `/api/sar/status`,
  `/api/ai/pins/geojson`, `/api/ai/pins`, and `/api/viewport` each return
  `403` before backend forwarding; the retained local `/api/health` returns
  `200` with its honest aggregate `error` state.
- EdPol exact-rule invocation completed with no blocking policy match. The
  candidate scan covered `125/126` files (favicon skipped by extension) and
  found `407` structural candidates only; each is manual context review, not a
  policy breach or AI-authorship finding.
- `git diff --check` and both AVDS audit-ledger validators pass after the
  report/evidence updates.

## Evidence layers

| Layer | Result | Identity / artifact |
| --- | --- | --- |
| Local source candidate | passed | Working tree on base `fe44b052…`; public contracts identify it as a dirty local candidate. |
| Local browser | passed | `output/playwright/shadowbroker-local-candidate-2026-08-23/` contains final compact `page-2026-08-23T17-23-53-231Z.png` and desktop `page-2026-08-23T17-14-13-190Z.png`. |
| Current public runtime baseline | not re-promoted | `https://shadow.qdev.run/release.json` remains `c9d63bc…`; it does not contain the current candidate. |
| AVDS runner | blocked by local tooling | The supplied runner cannot resolve its `playwright` package from the skill directory. Manual Playwright CLI evidence is retained, but it is not represented as an AVDS runner acceptance certificate. |

## Known, truthful runtime condition

`/api/health` is HTTP `200` with aggregate `status:error` while optional source
SLOs remain red. The candidate calls this **degraded**, never available/green.
Repairing upstream source freshness is outside this checkout and was not masked
in UI or reports.

## Non-local blockers

See `platform-integration-2026-08-23.md` for the stale external AVDS registry,
authenticated Platform schema/registry, bilateral QazStack proof and GitHub
write-access owners. They are not converted into coverage claims here.
