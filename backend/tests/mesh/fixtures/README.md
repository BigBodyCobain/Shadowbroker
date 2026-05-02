# MLS Test Vector Fixtures

Static test vectors for the privacy-core MLS bridge and mesh protocol
validation paths. These fixtures are loaded by `test_mls_vectors.py` and
`test_fault_injection.py` and run on every PR.

## Files

| File | Purpose |
|------|---------|
| `gate_mls_vectors.json` | Gate lifecycle: compose, encrypt, decrypt, add/remove member, rekey, epoch advance |
| `dm_mls_vectors.json` | DM lifecycle: key package export, session initiate/accept, encrypt/decrypt, welcome seal/unseal |
| `schema_rejection_vectors.json` | Malformed payloads that MUST be rejected by the schema registry |
| `fault_injection_vectors.json` | Corrupted, downgraded, tier-spoofed, and replayed messages for the fault-injection corpus |
