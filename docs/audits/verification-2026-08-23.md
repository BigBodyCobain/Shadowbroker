# ShadowBroker verification record — deployed public candidate

Date: 2026-08-23. Deployed source/runtime revision:
`c9d63bcb40f9d8f7d7fa3c1372376ba478518adf`; `sourceDirty` is `false`.
The frontend image is `sha256:4d471c71dfb240a5db542e6c9914482ce9aa492d269d4a86d3d48dab484ec1c9`.
The release was staged immutably on the origin, after a verified backend-volume
backup, then the frontend was recreated only after its production build passed.

## Passed

- `node --check frontend/scripts/generate-public-contracts.cjs`, JSON parsing
  for manifest/adoption/release contracts, and `git diff --check`.
- `npm run contracts:generate` and `npm run build` for the previous candidate,
  then the final origin Docker `npm run build`, which generated public contracts
  for `c9d63bc…` and built the published image.
- Focused frontend tests for the public-runtime and Sentinel boundaries: `4`
  files / `42` tests, plus the final onboarding regression subset: `2` files /
  `9` tests, all passed.
- Targeted lint of every changed UI and contract-generation surface: `0`
  errors and `0` warnings.
- AVDS anti-generative and visual-craft audit ledgers both pass their supplied
  validators with no unresolved findings.
- Public browser pass at `390x844`: exactly one H1 (`ShadowBroker`), `MAP
  LAYERS` is an H2, public credential onboarding is absent, the health surface
  truthfully says `Data service degraded`, and the console has `0` errors.
- Public HTTP proof: `/`, `/api/health`, `/release.json` and
  `/.well-known/qdev-project.json` return `200`; public `release.json` names
  `c9d63bc…` for both source and runtime.
- Bundled Python 3.12 `compileall` for `backend`.
- In a clean temporary checkout with no user data and
  `MESH_ALLOW_RAW_SECURE_STORAGE_FALLBACK=true`:
  `test_regen_duplicate_routes_baseline.py`, `test_no_new_duplicate_routes.py`
  and the health smoke test passed (`7 passed`).

## Evidence and known boundaries

`/api/health` returns HTTP 200 with its documented aggregate state `error`
while data is warming or optional source SLOs are red; the UI represents this
as the non-fabricated `degraded` state. It is not used as a claim of full data
availability.

The final public AVDS alias is an external stale registry record (0/4), not a
copy of the deployed project contract. It remains blocked in the Platform
integration report and is not treated as coverage evidence.

## Non-blocking lint and typecheck debt

The full `npm run lint` command finishes with `0 errors` and `202` legacy
warnings. The remaining warnings are concentrated in unmodified mesh, tests,
AI, map and legacy UI code. The candidate introduces none on its changed
surface and the warnings do not block the type-checked production build; they
remain P3 maintenance debt and are not presented as a clean lint baseline.

Raw `npx tsc --noEmit` also includes the test fixtures under a compiler
configuration that does not load their test-runner globals. Its remaining
diagnostics are pre-existing test-harness/fixture debt; the actual production
typecheck is the successful `npm run build`. A separate test `tsconfig` with
the runner types is needed before that ad-hoc command can serve as a gate.

## Full-suite boundary

The same clean checkout's complete backend suite produced `2469 passed`,
`252 failed`, `15 skipped`. This is baseline debt outside the closed findings,
not evidence that the local candidate is fully regression-clean.

| Blocker | Owner | Required closure proof |
| --- | --- | --- |
| Mesh/MLS failures require `privacy-core` shared-library output; the source exists in `privacy-core/`, but no Rust/Cargo toolchain or compiled dylib is available in this environment. | Privacy-core/runtime owner | Reproducible Rust build receipt and matching `libprivacy_core.dylib`, then a clean full-suite result. |
| Remaining mesh privacy failures include incompatible expectations around redaction, alias continuity, signed-write and transport contracts. Changing either side without a reviewed contract would risk weakening safety controls. | Product security maintainer | Reconciled canonical security contract, explicit expected-output decisions, and passing focused suites followed by a clean full run. |
| Running tests directly in the canonical checkout reads its encrypted local custody data and requires the unavailable `MESH_SECURE_STORAGE_SECRET`. | Local runtime-data owner | A disposable isolated test-data configuration or an authorised test secret; the private data itself was neither read nor modified. |

The blocked rows are not promoted to `covered`; they remain external or
baseline limitations, not release-identity evidence.
