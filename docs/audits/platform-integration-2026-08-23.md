# ShadowBroker Platform integration audit — final local candidate

Date: 2026-08-23. Canonical checkout: `BigBodyCobain/Shadowbroker` on `main`,
base `fe44b052b08547aa57b030e45a3fc0fb2f946b87`, with an intentionally dirty
working-tree candidate. No commit, push, deployment, or production restart was
performed in this audit cycle.

## Before evidence and boundary

Before the local changes, the public runtime at `https://shadow.qdev.run`
returned `200` for `/`, `/api/health`, `/release.json`, and both well-known
contracts. Its public release identity remains
`c9d63bcb40f9d8f7d7fa3c1372376ba478518adf`, not this local candidate. Browser
evidence recorded public `MKT OFF`, System Settings, Time Machine controls and
operator panels. The health payload is HTTP `200` with aggregate `status:error`
because two optional source SLOs are red; that is a degraded data condition, not
a successful-green claim.

## Local findings closed

| Finding | Priority | Closure proof |
| --- | --- | --- |
| Public composition exposed operator, AI, market and configuration controls. | P1 | `page.tsx` renders those surfaces only outside `isPublicReadOnlyRuntime()`; final compact and desktop browser evidence has no System Settings, Operator shell, `MKT`, or AI brief. |
| Public browser polled Time Machine and operator-owned SAR/AI data paths. | P1 | `useTimeMachine` no longer starts a module-global refresh; Maplibre and Worldview suppress `/api/ai/timemachine/*`, `/api/sar/*`, and `/api/ai/pins/*` in public mode. Final request log contains none. |
| Direct public API requests still inherited the server-side admin path and returned SAR/AOI or AI data. | P1 | The catch-all proxy now rejects sensitive, SAR, AI and viewport routes for `shadow.qdev.run` before forwarding. Local candidate probes of `/api/sar/aois`, `/api/sar/status`, `/api/ai/pins/geojson`, `/api/ai/pins`, and `/api/viewport` all return `403`; six proxy-boundary regression cases pass. |
| Public map posted viewport bounds although its backend path is not needed for the read-only projection. | P2 | `MaplibreViewer` disables backend viewport synchronisation in public mode; final request log contains no `POST /api/viewport`. Client-side bounds still drive local map culling. |
| Public read-only mode allowed private layer affordances (SAR, AI pins and Shodan). | P2 | Public layer composition removes the three controls and forces the corresponding map sources off. |
| Slow health responses could be aborted after eight seconds, leaving a permanent checking/unavailable state. | P2 | `OperationalStatus` retains the request until completion and ignores stale unmounted results. The new Strict Mode regression test passes; final browser state is `Data service degraded` with the live record count. |
| Market ticker and its opt-in control distracted from the OSINT-map task and invited a server-side side effect. | P2 | The ticker, `MKT` control and AI summary trigger are operator-only; the public news feed remains readable. |

## Contract status matrix

| Surface | Actual status | Evidence |
| --- | --- | --- |
| Project identity, lifecycle, owner and repository | documented | Root `qdev-project.json` declares canonical identifiers and public endpoints. |
| AVDS adapter | documented locally; conflicting externally | Local build generates a 4/4 static semantic adapter contract. The public AVDS edge alias is still stale (0/4). |
| QazPipe, QazLake, QazCompute, QazGeo and identity | not applicable, review-owned | Each capability has `product-maintainer`, rationale, and `reviewAt: 2026-11-23` in `qdev-project.json`. |
| QazStack bilateral registration | unverifiable | No project-side consumer contract is declared and the authenticated external registry/schema was unavailable. |
| Data/privacy public projection | covered in local candidate | Public browser exposes map layers and health only; operator-owned routes and controls are suppressed before a request is made. |
| Health, release identity and observability | documented locally | Build regenerates public contracts from canonical inputs. Public runtime remains the older `c9d63bc…`; no promotion claim is made. |
| Security and mutation protection | covered in local candidate | Existing proxy/API boundary remains in force; this change also removes public mutation affordances and unnecessary POSTs. |
| Delivery | local-only candidate | Type-checked production build and 812 frontend tests pass; publication was out of scope. |

## External closures still blocked

| Finding | Priority | Owner | Canonical external path and required proof |
| --- | --- | --- | --- |
| Public AVDS edge alias reports stale 0/4 data and image `sha256:a17c…`. | P1 | Platform AVDS registry owner | `/var/www/avds-badge-control/v1/shadowbroker.json`: publish the deployed project-built `frontend/contracts/avds-adoption.json`; public alias `evidence.source_revision` and `runtime_revision` must match the actual released runtime. |
| Platform schema and registry are authenticated HTML entrypoints from this checkout. | P2 | Platform registry owner | Canonical authenticated schema and ShadowBroker registry row: provide a schema-validation receipt and a record matching `qdev-project.json`. |
| Bilateral QazStack relationship has no external registry confirmation. | P2 | Platform registry owner and product maintainer | Reconcile the registry record with the project manifest and a consumer-contract decision; only matching records close the relationship. |
| Remote GitHub credential previously returned HTTP 403. | P2 | `BigBodyCobain/Shadowbroker` repository administrator | Grant write access or publish the audited source; remote branch must contain the intended revision. This cycle did not retry push. |

All locally actionable P1/P2 findings found in this cycle are closed. The rows
above remain `blocked`, not covered, because they require an external owner.
