# ShadowBroker InfoNet Threat Model

ShadowBroker v0.9.7 ships InfoNet and Wormhole as an experimental testnet.
This document is the release-facing threat model for those systems. It is
intended to keep README, UI, and release claims aligned with the implementation.

## Privacy Classification

| Surface | Classification | Notes |
|---|---|---|
| Meshtastic and APRS | Public | Radio traffic is public by design and can be intercepted by anyone in range or by public relays. |
| InfoNet gate chat | Content-encrypted, metadata visible | Messages are MLS-encrypted plus an AES-256-GCM envelope keyed from a per-gate secret. Members on other nodes read the room only after another member sends them that secret inside an end-to-end encrypted DM (gate invite) and they accept it. Gate id, key epoch, per-message sender tag and minute-rounded timestamp stay visible; anyone holding the gate secret reads all envelopes encrypted under it. |
| Dead Drop DMs | Strongest current lane | Token-based epoch mailboxes, SAS verification, sealed payloads, and witness/root checks improve privacy, but this is still testnet code. |
| Sovereign Shell governance | Public ledger | Petitions, votes, upgrades, disputes, and market events are intentionally observable signed records. |
| Privacy-core primitives | Integration runway | Rust MLS/private primitive work is present, but the README must not claim final RingCT, stealth, DEX, or anonymous-citizenship privacy until wired and audited. |

## In Scope

- Passive observation of public map layers and public mesh/gate traffic.
- Replay and duplicate write attempts against signed mesh endpoints.
- Basic sender spoofing attempts where canonical signatures are required.
- Local runtime mistakes such as leaking caches, operator keys, relay state, or hidden-service material through Git.
- Update-channel integrity checks for release zip assets and optional SHA-256 pins.

## Gate Key Distribution

- A gate secret moves between nodes only as a control frame inside an end-to-end encrypted DM. The frame is stripped on decrypt and never reaches the browser or mailbox; pending invites are stored in the sensitive (custody-wrapped) domain store.
- Invites go only to existing DM contacts whose trust state is not `mismatch` or `continuity_broken`; the recipient's operator must accept. The UI shows the sender's trust level and advises SAS comparison before accepting from an unverified contact.
- Rotation sends the new secret to every contact the key was granted to, minus excluded peers. A rotation is applied automatically only when it comes from the member the current key was accepted from; others wait for manual acceptance. Applying a rotation forwards it to the node's own grantees, minus the sender and the excluded list.
- Removal is only as complete as the grant tree: a removed member keeps every envelope encrypted before the rotation, and a member who invited them must also honour the exclusion. Ban/kick rotations redistribute to all grantees and do not exclude anyone automatically; use rotation with an explicit exclusion list to remove a remote member.
- Gate secrets give no forward secrecy beyond rotation: whoever holds a secret reads every envelope encrypted under it.

## Transport Floors

- DM and gate release require `private_strong` (Tor and RNS) when RNS is enabled on the node, and `private_transitional` (Tor) otherwise. Gate publication already prefers Tor, with RNS as the fallback carrier.

## Out Of Scope For v0.9.7

- A guarantee of end-to-end private messaging across every lane.
- Strong anonymity against a global network observer.
- Protection from a compromised local host, browser profile, or operator machine.
- Production-grade governance finality or financial settlement guarantees.
- Fully selected and audited privacy primitives for RingCT, stealth addresses, shielded balances, range proofs, or DEX matching.

## Required Operator Guidance

- Do not send sensitive material on public mesh, InfoNet gate chat, or experimental DMs.
- Only accept gate invites from contacts you have verified, and rotate the gate key with an exclusion list when a member should lose access.
- Treat all v0.9.7 mesh lanes as testnet lanes.
- Keep runtime keys, relay state, Tor hidden-service data, and `backend/data/*` operator state out of Git.
- Use the release zip asset for v0.9.6 auto-update compatibility, and prefer signed/hashed release artifacts where available.
