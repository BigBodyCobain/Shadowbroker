# ShadowBroker InfoNet Threat Model

ShadowBroker v0.9.7 ships InfoNet and Wormhole as an experimental testnet.
This document is the release-facing threat model for those systems. It is
intended to keep README, UI, and release claims aligned with the implementation.

## Privacy Classification

| Surface | Classification | Notes |
|---|---|---|
| Meshtastic and APRS | Public | Radio traffic is public by design and can be intercepted by anyone in range or by public relays. |
| InfoNet gate chat | Obfuscated, not private | Gate personas, canonical signing, padding, and transport policy reduce casual linkage but do not provide end-to-end encryption or metadata privacy. |
| Dead Drop DMs | Strongest current lane | Token-based epoch mailboxes, SAS verification, sealed payloads, and witness/root checks improve privacy, but this is still testnet code. |
| Sovereign Shell governance | Public ledger | Petitions, votes, upgrades, disputes, and market events are intentionally observable signed records. |
| Privacy-core primitives | Integration runway | Rust MLS/private primitive work is present, but the README must not claim final RingCT, stealth, DEX, or anonymous-citizenship privacy until wired and audited. |

## In Scope

- Passive observation of public map layers and public mesh/gate traffic.
- Replay and duplicate write attempts against signed mesh endpoints.
- Basic sender spoofing attempts where canonical signatures are required.
- Local runtime mistakes such as leaking caches, operator keys, relay state, or hidden-service material through Git.
- Update-channel integrity checks for release zip assets and optional SHA-256 pins.

## Out Of Scope For v0.9.7

- A guarantee of end-to-end private messaging across every lane.
- Strong anonymity against a global network observer.
- Protection from a compromised local host, browser profile, or operator machine.
- Production-grade governance finality or financial settlement guarantees.
- Fully selected and audited privacy primitives for RingCT, stealth addresses, shielded balances, range proofs, or DEX matching.

## Required Operator Guidance

- Do not send sensitive material on public mesh, InfoNet gate chat, or experimental DMs.
- Treat all v0.9.7 mesh lanes as testnet lanes.
- Keep runtime keys, relay state, Tor hidden-service data, and `backend/data/*` operator state out of Git.
- Use the release zip asset for v0.9.6 auto-update compatibility, and prefer signed/hashed release artifacts where available.
