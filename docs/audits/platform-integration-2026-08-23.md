# ShadowBroker Platform integration audit — deployed baseline and final local candidate

Date: 2026-08-24. Canonical checkout: `BigBodyCobain/Shadowbroker` on `main`.
The final local candidate is code revision
`809271c6950c23014837b17f26bf23867fb399b6`, with attestation commit
`4a78cccb1a5c7a008799780bd0a849c007ee64a1`. Unrelated `output/` artifacts
remain untracked and were preserved.

## Before evidence and deployment record

Before this cycle, `https://shadow.qdev.run` exposed public operator, AI,
market, Time Machine, and configuration surfaces; sensitive proxy routes also
returned `200`. The first deployed read-only release was
`ef6fea05b528d9808b1141f345f39faec333e73f`: its release identity and edge AVDS
record matched, and direct public probes of SAR, AI, Time Machine, Shodan and
viewport mutation routes returned `403`.

The final browser pass against that deployed baseline found one remaining P1:
React hydration error `#418`. Server-side rendering treated the host as an
operator runtime while the browser switched to public read-only mode. The
`809271c` candidate passes `NEXT_PUBLIC_PUBLIC_READ_ONLY=true npm run build`
and makes that projection a Docker build-time contract. Its deployment and
post-fix browser recheck are deferred by the active Hostinger CPU limit on the
runtime host; the in-progress source transfer was interrupted and no runtime
process was left running for this candidate.

## Findings and closure state

| Finding | Priority | State and proof |
| --- | --- | --- |
| Public composition exposed operator, AI, market and configuration controls. | P1 | Closed in deployed `ef6`: public composition omits these surfaces; browser counted `0` System Settings, Operator and `MKT` controls. |
| Public browser polled private Time Machine, SAR and AI routes. | P1 | Closed in deployed `ef6`: public controls and polling are suppressed; direct public operator routes return `403`. |
| Public map posted viewport bounds and retained private layer affordances. | P2 | Closed in deployed `ef6`: public mode disables backend viewport sync and hides SAR, AI-pin and Shodan controls. |
| Slow health checks produced a permanent unavailable presentation. | P2 | Closed in deployed `ef6`: `OperationalStatus` retains the request until completion; its regression coverage passes. |
| Public SSR and browser hydration disagreed about the read-only projection. | P1 | Fixed locally in `809271c`: `frontend/Dockerfile` accepts and inlines `NEXT_PUBLIC_PUBLIC_READ_ONLY`; canonical deploy override sets it to `true`. Local production build and all 818 frontend tests pass. Deployment proof is deferred by the host limit. |
| Production image lacked a usable browser runtime. | P1 | Closed on the deployed baseline: image build verifies the non-root Playwright browser and headless shell; runtime launch succeeded before the host restriction. |
| Origin deployment health check targeted removed `/api/liveness`. | P1 | Closed on the deployed baseline: health check now targets `/api/health`; backend reached `healthy`. Canonical override carries the same endpoint. |

## Contract status matrix

| Surface | Actual status | Evidence |
| --- | --- | --- |
| Project identity, lifecycle, owner and repository | documented | Root `qdev-project.json` declares canonical identifiers and public endpoints. |
| AVDS adapter and edge record | deployed baseline covered | The deployed edge record matched `ef6…`; candidate input is attested for `809…`. Final candidate browser acceptance remains pending. |
| QazPipe, QazLake, QazCompute, QazGeo and identity | review-owned | Manifest declares each capability with `product-maintainer`, rationale and a review date. |
| Data/privacy public projection | deployed baseline covered | Public route and browser evidence show read-only projection; privileged routes are denied before backend forwarding. |
| Health, readiness and release identity | partially covered | Backend container was healthy and identity matched `ef6…`; the last observed source-health payload honestly reported degraded/error upstream data. The `809…` candidate is not promoted. |
| Security and mutation protection | deployed baseline covered | Public sensitive routes and viewport mutation requests are denied with `403`. |
| Delivery | local candidate pending promotion | Production build and 818 tests passed for `809…`; remote deployment is intentionally paused by the active host CPU restriction. |

## Remaining external dependency

The only open P1 is the final `809…` promotion and browser acceptance. External
owner: runtime infrastructure owner. Dependency: removal of the current
Hostinger CPU limit for the excluded runtime host. Closure proof required: a
successful image rebuild/recreate, healthy container, matching release and AVDS
identities, and mobile plus desktop browser runs with no hydration error.
