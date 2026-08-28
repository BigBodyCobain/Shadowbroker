# ShadowBroker organ extraction and retirement

ShadowBroker is a temporary donor and compatibility consumer. Its final state is
decommissioned, not a second collection or platform implementation.

The machine-readable source of truth is
`config/shadow_organ_ledger.json`. Every donor area must have one explicit
disposition: migrate to an existing canonical owner, adapt after a gate, archive
as non-production evidence, reject, or retire. Secrets, provider sessions, raw
protected records, topology, generated datasets and compiled artifacts are not
organs and must not be copied through Git.

## Canonical routing

- QazPipe owns approved anonymous recurring collection; QazLake owns DDL,
  append-only observations and protected consumer feeds.
- QazFin owns finance and prediction-market collection.
- QazStack may own only provider-neutral contracts with a platform mandate or
  two real consumers. Product weights, cases, storage and transport stay out.
- AVDS already owns source health, freshness and map-layer controls. A new
  primitive is allowed only after an exact catalog gap, two consumers, a pilot,
  rollback and return-to-donor evidence.
- Credential/session/operator sources require a named protected successor or an
  explicit retirement decision before Shadow deletion.

## Retirement sequence

1. Finish QazLake feed deployment and security proof, then QazPipe inactive
   canaries and Shadow compare mode under the original cutover gates.
2. Move each accepted data family to its canonical owner sequentially. Record
   schedule stop/start, watermark, comparison and rollback receipts.
3. Release extracted shared contracts and adopt them in a non-Shadow consumer.
   Archive rejected experimental code with its warnings, never as a production
   security package.
4. Inventory exact runtime resources, export only allowed audit/rollback
   evidence, revoke or rotate every Shadow credential, disable ingress and
   schedules, and observe one full cadence plus the 24-hour window.
5. Delete only the signed exact resource list. Keep immutable release manifests,
   final source archive and rollback evidence outside the retired runtime.

Deletion is blocked by any unresolved source right, live consumer, credential,
dead letter, schema error, stale watermark, public/private contract regression or
missing exact resource inventory.
