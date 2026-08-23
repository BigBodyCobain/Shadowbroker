# ShadowBroker Platform integration audit — local candidate

Date: 2026-08-23. Scope: the canonical `BigBodyCobain/Shadowbroker` checkout at
`2fca1a494aace994fba95dde1fc8dde9e4c7a664`, plus its public entrypoint as
read-only before evidence. No deployment was authorised or performed.

## Fixed in this candidate

| Finding | Priority | Closure proof |
| --- | --- | --- |
| No project-side Platform identity or capability declaration | P1 | Root `qdev-project.json` now declares the experimental lifecycle, repository, owner, public endpoints, data boundary, capability decisions and verification commands. |
| No deployable project-side public contracts | P1 | `frontend/scripts/generate-public-contracts.cjs` generates `.well-known/qdev-project.json`, `.well-known/avds-adoption.json`, and `release.json` from canonical inputs during `prebuild`. |
| Public health state was represented by decorative UI activity | P1 | `OperationalStatus` reads `/api/health`, exposes loading, available, degraded and unavailable states, and never substitutes invented metrics. |
| Capability decisions lacked review ownership | P2 | Each currently non-applicable QazPipe, QazLake, QazCompute, QazGeo and identity decision carries a product-maintainer owner and `2026-11-23` review date. |
| CI collected a test for a missing duplicate-route baseline generator | P1 | Added `backend/scripts/regen_duplicate_routes_baseline.py`; its three direct tests pass. |
| `/api/wormhole/dm/contact/{peer_id}/sever` was newly registered in both `main.py` and the router | P1 | Removed the shadowed `main.py` handler, preserving the router-owned protected handler. The no-new-duplicates guard passes in a clean test checkout. |
| The fresh-store health smoke test assumed an `ok` state despite the documented SLO contract returning `error` before sources have fetched | P2 | The smoke test now accepts the three defined health states rather than asserting a fabricated ready state. |
| Public map and feed data crossed component boundaries as loosely typed payloads, including coordinates that could be malformed | P2 | Canonical dashboard contracts now name the flight, news, Shodan and AI-pin fields; map/feed adapters reject invalid coordinates before rendering. Final production build and `808` frontend tests pass. |
| The map page exposed two H1 headings and the first-run/release dismiss controls had no accessible name | P2 | `ShadowBroker` remains the sole H1, `MAP LAYERS` is an H2, and each close control has an explicit accessible label. The `390x844` browser snapshot exercises all three labels. |

## External closure still required

| Finding | Priority | State | External owner and required proof |
| --- | --- | --- | --- |
| The public `https://shadow.qdev.run/api/health` probe timed out before the candidate work; `/release.json` was not published. | P1 | blocked | Deployment/runtime operator must deploy this candidate, return an HTTP 200 health body, and publish `release.json` whose `sourceRevision` and `runtimeRevision` identify the deployed build. |
| The live `.well-known/avds-adoption.json` reported 0/4 implementation for a prior runtime. | P1 | blocked | Deployment/runtime operator must publish the generated candidate contract and prove its response matches the deployed release identity. |
| Platform schema and registry endpoints returned an authenticated HTML entrypoint rather than the requested JSON/schema. | P2 | blocked | Platform registry owner: validate `qdev-project.json` against the canonical authenticated schema and add or reconcile the `shadowbroker` registry row. Closure proof is a schema-validation receipt plus the matching registry record. |
| Bilateral Platform/QazStack registration cannot be asserted from this checkout. | P2 | blocked | Platform registry owner and product maintainer must reconcile the external registry record with the project manifest. Until then, those relationships are intentionally not declared covered. |

`qdev-project.json` records the schema result as `unverifiable`, rather than asserting compliance without the authenticated schema.
