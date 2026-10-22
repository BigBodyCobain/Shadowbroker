# Sharing a Gate Across Nodes

Every node generates its own key for each gate. Until two operators share a
key, neither can read the other's posts in that gate. Gate invites share it.

## Inviting someone

1. Add them as a DM contact first (exchange DM invites in **Messages**), and
   compare safety codes (SAS) if you need to be sure who they are.
2. Open the gate, expand **GATE KEY SHARING**, choose the contact and press
   **SEND KEY**. The key travels inside an end-to-end encrypted DM.
3. They see a `[Gate key]` notice in their mailbox and a pending entry under
   **GATE INVITES** (in Messages or the gate's key panel). Once they press
   **ACCEPT**, both nodes read each other's posts in that gate, including
   posts made before the invite.

The panel header shows a short key fingerprint (`key 1a2b3c4d`). Two members
showing the same fingerprint hold the same key.

## Rotating and removing members

- **ROTATE KEY** makes a new key and sends it to everyone you shared the key
  with. Members apply a rotation automatically when it comes from the person
  who gave them the key, and pass it on to the people they invited.
- To remove someone, rotate with their peer id excluded:
  `POST /api/wormhole/gate/key/rekey` with
  `{"gate_id": "...", "exclude_peer_ids": ["!sb_..."]}`. They keep everything
  posted before the rotation and lose everything after it.
- A rotation that reaches you from anyone other than your upstream member
  waits under **GATE INVITES** for you to accept or decline.

## API

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/wormhole/gate/invite` | `{gate_id, peer_id, note?}`: send the current key to a contact |
| GET | `/api/wormhole/gate/invites` | Pending invites and rotations (no secrets) |
| POST | `/api/wormhole/gate/invite/accept` | `{invite_id}` |
| POST | `/api/wormhole/gate/invite/decline` | `{invite_id}` |
| POST | `/api/wormhole/gate/key/rekey` | `{gate_id, exclude_peer_ids?}`: rotate and redistribute |
| GET | `/api/wormhole/gate/{gate_id}/key/sharing` | Fingerprint, upstream and grantees |

All routes are local-operator only.

## Transport

Gate posts release over Tor (`private_transitional`). If you enable
Reticulum on the node (`MESH_RNS_ENABLED=true`, with the `rns` Python package
installed and `MESH_RNS_PEERS` configured), the floor rises to Tor plus RNS
(`private_strong`).

See [threat-model.md](threat-model.md) for what this does and does not
protect.
