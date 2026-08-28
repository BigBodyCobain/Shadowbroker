# ShadowBroker organ extraction and retirement

ShadowBroker is a temporary donor and compatibility consumer. Its final state is
decommissioned, not a second collection or platform implementation.

The machine-readable source of truth is
`config/shadow_organ_ledger.json`. Every donor area must have one explicit
disposition: migrate to an existing canonical owner, adapt after a gate, archive
as non-production evidence, reject, or retire. Secrets, provider sessions, raw
protected records, topology, generated datasets and compiled artifacts are not
organs and must not be copied through Git.

`python3 scripts/verify_shadow_organ_ledger.py` is the fail-closed coverage
check. It requires all eleven review planes, verifies every donor locator, and
classifies every path in the immutable 1,222-file donor Git tree by primary
organ and disposition. The count and sorted-path SHA-256 are revision-bound, so
an omitted module, stale inventory or empty classification rule fails the gate.
It also prevents a `ready` retirement state while blockers remain. CI runs it
before backend tests so new Shadow surfaces cannot silently escape disposition.

## Canonical routing

- QazPipe owns approved anonymous recurring collection; QazLake owns DDL,
  append-only observations and protected consumer feeds.
- QazFin owns finance and prediction-market collection.
- QazStack may own only provider-neutral contracts with a platform mandate or
  two real consumers. Product weights, cases, storage and transport stay out.
- AVDS already owns source health, freshness and map-layer controls. A new
  primitive is allowed only after an exact catalog gap, two consumers, a pilot,
  rollback and return-to-donor evidence.
- Credential/session/operator sources have no approved post-Shadow owner. The
  recorded terminal decision is to stop them, revoke their credentials and
  retire them with Shadow after exact feed and schedule inventory. No source,
  session, protected record or secret is copied. A separately approved successor
  before cutover would require a new owner-specific gate and receipt.

The exact reuse scan is recorded in `reuse_decisions` in the organ ledger.
Only the provider-neutral feed-cutover receipt is a confirmed shared gap.
QazStack already owns early-warning, temporal and HMAC/replay contracts, while
AVDS already owns the source-state and map-control primitives. Shadow-specific
weights, cases, stores, terminal styling and operator workflows therefore do
not become new platform modules. Only redacted contracts and synthetic golden
fixtures may be archived; anything without an approved successor retires with
Shadow.

## Retirement sequence

1. Finish QazLake feed deployment and security proof, then QazPipe inactive
   canaries and Shadow compare mode under the original cutover gates.
2. Move each accepted data family to its canonical owner sequentially. Record
   schedule stop/start, watermark, comparison and rollback receipts.
3. Release extracted shared contracts and adopt them in a non-Shadow consumer.
   Archive rejected experimental code with its warnings, never as a production
   security package.
4. Inventory exact runtime resources and every credential/session/operator
   feed. Export only allowed audit/rollback evidence; then stop and verify those
   schedules, revoke or rotate every Shadow credential, disable ingress, and
   observe one full cadence plus the 24-hour window. Closed feeds and protected
   records are retired, not transferred.
5. Delete only the signed exact resource list. Keep immutable release manifests,
   final source archive and rollback evidence outside the retired runtime.

The protected retirement receipt uses
`shadowbroker-retirement-receipt/v1`. Verify it from outside the Shadow runtime
with an independently retained Ed25519 trust anchor:

```bash
.venv/bin/python scripts/verify_shadow_retirement_receipt.py \
  /protected/retirement/shadowbroker.json \
  --public-key /protected/retirement/shadowbroker-retirement-public.pem
```

The receipt must enumerate every service, container, image, ingress, checkout,
schedule, secret binding and volume by exact locator and immutable identity in a
contiguous deletion order. It also retains hashes for the final release,
rollback and audit artifacts and records only credential action evidence, never
secret values. Wildcards, parent traversal, shell expansion and broad paths are
rejected before signature verification.

Deletion is blocked by any unresolved source right, live consumer, credential,
dead letter, schema error, stale watermark, public/private contract regression or
missing exact resource inventory.
