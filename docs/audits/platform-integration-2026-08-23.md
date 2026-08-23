# ShadowBroker Platform integration audit — deployed candidate

Date: 2026-08-23. Scope: the canonical `BigBodyCobain/Shadowbroker` checkout
and `https://shadow.qdev.run`. The deployed source and runtime revision is
`c9d63bcb40f9d8f7d7fa3c1372376ba478518adf`, with `sourceDirty: false`.

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
| Frontend delivery could not see root-level `qdev-project.json`; origin Compose also requested two CPUs and probed a non-existent liveness endpoint | P1 | Root build context, the release-only Compose override, a one-CPU backend limit, and `/api/health` container probe build and start both services on the actual origin host. |
| The public browser polled six operator-only endpoints, producing harmless but misleading 403 console errors | P2 | The public-host boundary now suppresses operator layer, API-key, agent-action, time-machine, prediction-market and LiveUAMap calls. Final browser evidence contains zero console errors. |
| First-time public onboarding invited unauthenticated visitors to enter API credentials | P1 | Public read-only runtime never opens the credential onboarding; local operator onboarding remains intact. Final mobile browser evidence confirms the form is absent. |

## External closure still required

| Finding | Priority | State | External owner and required proof |
| --- | --- | --- | --- |
| The live `.well-known/avds-adoption.json` still reports 0/4 and image digest `sha256:a17c…`, while this release exposes `c9d63bc…`. | P1 | blocked | Platform AVDS registry owner must publish the project-built `frontend/contracts/avds-adoption.json` to the edge alias at `/var/www/avds-badge-control/v1/shadowbroker.json`; proof: public alias content and its `evidence.source_revision` match this release. |
| Platform schema and registry endpoints returned an authenticated HTML entrypoint rather than the requested JSON/schema. | P2 | blocked | Platform registry owner: validate `qdev-project.json` against the canonical authenticated schema and add or reconcile the `shadowbroker` registry row. Closure proof is a schema-validation receipt plus the matching registry record. |
| Bilateral Platform/QazStack registration cannot be asserted from this checkout. | P2 | blocked | Platform registry owner and product maintainer must reconcile the external registry record with the project manifest. Until then, those relationships are intentionally not declared covered. |
| The canonical local commits cannot be pushed to `BigBodyCobain/Shadowbroker` with the configured credential (GitHub returned HTTP 403). | P2 | blocked | GitHub repository administrator for `BigBodyCobain/Shadowbroker` must grant write access or push the listed commits; proof: remote branch contains `c9d63bc…` (or its audited equivalent). |

`qdev-project.json` records the schema result as `unverifiable`, rather than asserting compliance without the authenticated schema.
