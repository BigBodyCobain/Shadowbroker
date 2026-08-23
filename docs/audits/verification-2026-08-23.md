# ShadowBroker verification record — deployed baseline and final local candidate

Date: 2026-08-24. Final local candidate: code
`809271c6950c23014837b17f26bf23867fb399b6`; contract attestation
`4a78cccb1a5c7a008799780bd0a849c007ee64a1`.

## Passed locally

- `NEXT_PUBLIC_PUBLIC_READ_ONLY=true npm run build` completed with generated
  contracts and TypeScript checks.
- `npm test -- --run`: `94` files and `818` tests passed.
- `git diff --check` passed before the report update.
- The Docker build change injects the public mode at build time, so server and
  browser render the same public projection.

## Last verified deployed baseline

- Release and AVDS edge identity matched
  `ef6fea05b528d9808b1141f345f39faec333e73f`.
- Backend was `healthy`; the packaged non-root runtime launched Chromium and
  its headless shell successfully.
- Public direct requests to SAR, AI pins, AI/Time Machine, Shodan and viewport
  mutation paths returned `403`; public health remained available.
- Mobile browser check returned `200`, had no `MKT`, System Settings or
  Operator controls, and included the explicit public Time Machine boundary.

## Finding carried into the final local candidate

That browser check reported React hydration error `#418`. The public client
correctly hid operator UI, but SSR had rendered the operator projection first.
`809271c` fixes this through `NEXT_PUBLIC_PUBLIC_READ_ONLY` in the Dockerfile
and canonical public deploy override. The old release is not falsely claimed as
the final browser-accepted candidate.

## Delivery status

No remote action is active. A source-transfer process was stopped when the
runtime host became excluded by its Hostinger CPU limit. Until that limit is
removed, the final candidate remains local-only and the required post-fix
release/browser proof is pending.
