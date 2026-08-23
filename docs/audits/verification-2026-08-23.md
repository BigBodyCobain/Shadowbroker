# ShadowBroker verification record — local candidate

Date: 2026-08-23. Candidate base revision:
`2fca1a494aace994fba95dde1fc8dde9e4c7a664`; working tree intentionally
dirty with the fixes recorded in this audit. No commit, push, deployment or
production restart was performed.

## Passed

- `node --check frontend/scripts/generate-public-contracts.cjs`, JSON parsing
  for manifest/adoption/release contracts, and `git diff --check`.
- `npm run contracts:generate` and the final `npm run build` in `frontend`;
  the production build compiled, type-checked and emitted the public-contract
  files from canonical inputs after all candidate changes.
- `npm test` in `frontend`: `90` test files and `808` tests passed.
- Targeted lint of every changed UI and contract-generation surface: `0`
  errors and `0` warnings.
- AVDS anti-generative and visual-craft audit ledgers both pass their supplied
  validators with no unresolved findings.
- Browser pass against the production-built local candidate at `390x844`:
  the page has one H1 (`ShadowBroker`), `MAP LAYERS` is an H2, the three
  first-run/release close controls have accessible names, and the unavailable
  service state leaves map controls available. The local frontend had no
  backend configured, so its `/api/*` requests returned `502`; this is
  truthful degraded-state evidence, not a healthy runtime acceptance.
- Bundled Python 3.12 `compileall` for `backend`.
- In a clean temporary checkout with no user data and
  `MESH_ALLOW_RAW_SECURE_STORAGE_FALLBACK=true`:
  `test_regen_duplicate_routes_baseline.py`, `test_no_new_duplicate_routes.py`
  and the health smoke test passed (`7 passed`).

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

The blocked rows are not promoted to `covered`; they remain local-candidate
limitations.
