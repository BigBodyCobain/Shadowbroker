# Wormhole DM Root Operations Runbook

This runbook covers the v0.9.7 operator flow for DM root witness and
transparency monitoring.

## Goals

- Keep root transparency state observable for operators.
- Make witness publication and monitoring repeatable.
- Avoid committing operator-local keys, ledgers, or runtime state.

## Local State Boundaries

Never commit these paths:

- `backend/data/root/`
- `backend/data/root_distribution/`
- `backend/data/root_transparency/`
- `backend/data/_domain_keys/`
- `ops/`
- `dm_relay.json`

The root `.gitignore` excludes these runtime paths. If a release archive is
made with `git archive`, only tracked files are included.

## Useful Scripts

Run these from the repository root after configuring the backend and any
operator environment variables required by the specific deployment:

```bash
node scripts/mesh/poll-dm-root-health-alerts.mjs
node scripts/mesh/export-dm-root-health-prometheus.mjs
node scripts/mesh/publish-external-root-witness-package.mjs
node scripts/mesh/smoke-external-root-witness-flow.mjs
node scripts/mesh/smoke-root-transparency-publication-flow.mjs
node scripts/mesh/smoke-dm-root-deployment-flow.mjs
node scripts/mesh/sync-dm-root-external-assurance.mjs
```

## Release Checklist

1. Run the secret scanner against the candidate tree.
2. Verify root transparency tests pass.
3. Verify no runtime root, witness, Tor, key, or relay-state files are staged.
4. Build release archives from the committed tree with `git archive`.
5. Attach `ShadowBroker_v0.9.7.zip` to the GitHub release for v0.9.6 updater compatibility.
