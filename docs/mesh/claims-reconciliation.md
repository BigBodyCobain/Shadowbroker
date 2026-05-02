# ShadowBroker Mesh Claims Reconciliation

This file maps high-level release claims to implementation status for v0.9.7.
It exists to prevent the public README from promising stronger privacy or
security than the code provides.

| Claim | Status | Implementation Notes |
|---|---|---|
| InfoNet is a decentralized intelligence mesh. | Supported as testnet | Mesh routing, signed events, peer sync, gate personas, and Wormhole relay code are present, but deployment topology is still experimental. |
| Gate chat is private. | Not supported | Gate chat is obfuscated and signed, not end-to-end private. Public claims must say "obfuscated" rather than "private". |
| Dead Drop DMs are the strongest current private lane. | Supported with caveats | DM mailboxes, token handling, SAS/contact verification, sealed payloads, and witness/root transparency code exist. The lane is still experimental and should not be described as confidently private. |
| Sovereign Shell governance is public. | Supported | Governance events are signed public records and should be documented as observable. |
| Function Keys provide anonymous citizenship proof. | Partial | Nullifiers, challenge-response, receipts, denial codes, and settlement scaffolding exist. Blind-signature issuance is not complete. |
| RingCT, stealth addresses, shielded balances, and DEX privacy are live. | Not supported | Protocol interfaces and Rust integration targets exist, but final primitives are not selected, wired, and audited. |
| v0.9.6 users can auto-update to v0.9.7. | Supported if release asset is attached | The v0.9.6 updater requires a `.zip` release asset. The v0.9.7 release must attach `ShadowBroker_v0.9.7.zip`. Future v0.9.7+ updaters can use GitHub `zipball_url`. |
| Docker users should update by pulling images. | Supported | The v0.9.7 updater detects Docker/runtime contexts and returns Docker pull instructions instead of attempting in-place extraction. |
