# ShadowBroker — Meshtastic MQTT Remediation

**Version:** 0.9.6  
**Date:** 2026-04-12  
**Re:** [meshtastic/firmware#6131](https://github.com/meshtastic/firmware/issues/6131) — Excessive MQTT traffic from ShadowBroker clients

---

## What happened

ShadowBroker is an open-source OSINT situational awareness platform that includes a Meshtastic MQTT listener for displaying mesh network activity on a global map. In prior versions, the MQTT bridge:

- Subscribed to **28 wildcard topics** (`msh/{region}/#`) covering every known official and community root on startup
- Used an aggressive reconnect policy (min 1s / max 30s backoff)
- Set keepalive to 30 seconds
- Had no client-side rate limiting on inbound messages
- Auto-started on every launch with no opt-out

This produced 1-2 orders of magnitude more traffic than typical Meshtastic clients on the public broker at `mqtt.meshtastic.org`.

---

## What we fixed

### 1. Bridge disabled by default

The MQTT bridge no longer starts automatically. Operators must explicitly opt in:

```env
MESH_MQTT_ENABLED=true
```

### 2. US-only default subscription

When enabled, the bridge subscribes to **1 topic** (`msh/US/#`) instead of 28. Additional regions are opt-in:

```env
MESH_MQTT_EXTRA_ROOTS=EU_868,ANZ
```

The UI still displays all regions in its dropdown — only the MQTT subscription scope changed.

### 3. Client-side rate limiter

Inbound messages are capped at **100 messages per minute** using a sliding window. Excess messages are silently dropped. A warning is logged periodically when the limiter activates so operators are aware.

### 4. Conservative connection parameters

| Parameter | Before | After |
|-----------|--------|-------|
| Keepalive | 30s | 120s |
| Reconnect min delay | 1s | 15s |
| Reconnect max delay | 30s | 300s |
| QoS | 0 | 0 (unchanged) |

### 5. Versioned client ID

Client IDs changed from `sbmesh-{uuid}` to `sb096-{uuid}` so the Meshtastic team can identify ShadowBroker clients and track adoption of the fix by version.

---

## Configuration reference

| Variable | Default | Description |
|----------|---------|-------------|
| `MESH_MQTT_ENABLED` | `false` | Master switch for the MQTT bridge |
| `MESH_MQTT_EXTRA_ROOTS` | _(empty)_ | Comma-separated additional region roots (e.g. `EU_868,ANZ,JP`) |
| `MESH_MQTT_INCLUDE_DEFAULT_ROOTS` | `true` | Include US in subscriptions |
| `MESH_MQTT_BROKER` | `mqtt.meshtastic.org` | Broker hostname |
| `MESH_MQTT_PORT` | `1883` | Broker port |
| `MESH_MQTT_USER` | `meshdev` | Broker username |
| `MESH_MQTT_PASS` | `large4cats` | Broker password |
| `MESH_MQTT_PSK` | _(empty)_ | Hex-encoded PSK (empty = default LongFast key) |

---

## Files changed

- `backend/services/config.py` — Added `MESH_MQTT_ENABLED` flag
- `backend/services/mesh/meshtastic_topics.py` — Reduced default roots to US-only
- `backend/services/sigint_bridge.py` — Rate limiter, keepalive/backoff tuning, versioned client ID, opt-in gate
- `backend/.env.example` — Documented all MQTT options

---

## Contact

Repository: [github.com/BigBodyCobain/Shadowbroker](https://github.com/BigBodyCobain/Shadowbroker)  
Maintainer: BigBodyCobain
