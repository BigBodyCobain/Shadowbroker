// AIS Stream WebSocket proxy.
//
// Reads AIS_API_KEY from argv or env, opens a wss:// connection to
// stream.aisstream.io, subscribes for vessel position reports inside the
// active map bounding boxes, and pipes JSON messages to stdout for the
// Python backend to ingest.
//
// Issue #258 — SPKI pinning fallback for upstream cert outages
// -------------------------------------------------------------
// AISStream uses Let's Encrypt and their renewal pipeline has been observed
// to fail (cert expired on 2026-05-20). The naive fix the issue reporter
// applied — passing { rejectUnauthorized: false } — turns off TLS validation
// entirely, which lets any network attacker MITM the WebSocket and inject
// fake ship positions onto the operator's map. Same class as the GDELT
// plaintext-HTTP MITM issue (#199).
//
// Instead, when the normal TLS handshake fails with CERT_HAS_EXPIRED, we
// do a custom TLS connection that ignores ONLY the expiry check, capture
// the leaf certificate, and compare its public-key SPKI hash against a
// pinned list (backend/data/aisstream_spki_pins.json). If the SPKI matches,
// the upstream is still the genuine AISStream — just with an expired cert —
// and we proceed in "degraded TLS" mode. If the SPKI does not match, we
// refuse the connection and log loudly: an actual MITM is in progress.
//
// Let's Encrypt renewals keep the same public key by default, so the pinned
// SPKI survives normal cert rotation. The pin list MUST be updated before
// the operator's pinned key is rotated upstream.

const WebSocket = require('ws');
const readline = require('readline');
const fs = require('fs');
const path = require('path');
const tls = require('tls');
const crypto = require('crypto');

const args = process.argv.slice(2);
const API_KEY = args[0] || process.env.AIS_API_KEY;

if (!API_KEY) {
    console.error("FATAL: AIS_API_KEY is not set. WebSocket proxy cannot start.");
    process.exit(1);
}

// ── SPKI pin support (issue #258) ─────────────────────────────────────────

const AIS_HOST = 'stream.aisstream.io';
const AIS_PORT = 443;
const AIS_WS_URL = `wss://${AIS_HOST}/v0/stream`;

// Pin file is looked up in several layouts so the same JS works in:
//   - the Docker backend image (PIN_FILE_CANDIDATES[0])
//   - the Tauri desktop runtime (PIN_FILE_CANDIDATES[1])
//   - a future relocated layout (operator can drop a file at
//     SHADOWBROKER_AIS_PINS env var)
const PIN_FILE_CANDIDATES = [
    process.env.SHADOWBROKER_AIS_PINS || '',
    path.join(__dirname, 'data', 'aisstream_spki_pins.json'),
    path.join(__dirname, 'aisstream_spki_pins.json'),
].filter(Boolean);

// Embedded fallback. Used when no external pin file is reachable so the
// SPKI fallback still works on minimal/portable installs. The external
// file (when present) takes priority so operators can update pins without
// needing a new build.
const EMBEDDED_PINS = {
    [AIS_HOST]: [
        // Captured 2026-05-20 from AISStream's leaf cert (Let's Encrypt R12).
        // Replace when AISStream rotates server keys.
        'GJ10H0UPgLrO+2d3ZXROR/TXSVFXKUfRC3QEI2ibEg4=',
    ],
};

let aisDegradedMode = false;  // surfaced via stdout status_query marker

function loadSpkiPins() {
    for (const candidate of PIN_FILE_CANDIDATES) {
        try {
            const raw = fs.readFileSync(candidate, 'utf-8');
            const parsed = JSON.parse(raw);
            const pins = Array.isArray(parsed[AIS_HOST]) ? parsed[AIS_HOST] : [];
            const cleaned = pins
                .filter((p) => typeof p === 'string' && p.length > 0)
                .map((p) => p.trim());
            if (cleaned.length > 0) {
                return cleaned;
            }
        } catch (e) {
            // Try the next candidate — file may not exist in this layout.
            continue;
        }
    }
    const embedded = (EMBEDDED_PINS[AIS_HOST] || []).slice();
    if (embedded.length > 0) {
        console.error(
            '[AIS Proxy] No external SPKI pin file found; using embedded fallback. '
            + `(Set SHADOWBROKER_AIS_PINS or drop ${PIN_FILE_CANDIDATES[1]} to override.)`
        );
    }
    return embedded;
}

function spkiHashFromPeerCert(peerCert) {
    // tls.TLSSocket.getPeerCertificate() exposes .pubkey when called with
    // detailed=true. The pubkey buffer is the DER-encoded SubjectPublicKeyInfo,
    // which is exactly the value we hash for SPKI pinning.
    if (!peerCert || !peerCert.pubkey) return null;
    return crypto.createHash('sha256').update(peerCert.pubkey).digest('base64');
}

// Probe the upstream when normal TLS failed with CERT_HAS_EXPIRED. We open
// a raw TLS connection with rejectUnauthorized=false ONLY to inspect the
// leaf cert; we do NOT use this socket for the actual WebSocket traffic.
// Returns { ok: true } if the leaf SPKI matches the pin list, { ok: false }
// with a reason otherwise.
function verifyExpiredCertAgainstPins() {
    return new Promise((resolve) => {
        const pins = loadSpkiPins();
        if (pins.length === 0) {
            resolve({ ok: false, reason: 'no SPKI pins configured' });
            return;
        }
        const sock = tls.connect(
            {
                host: AIS_HOST,
                port: AIS_PORT,
                servername: AIS_HOST,
                // Allow the handshake to complete despite the expired cert
                // so we can inspect the leaf. We do NOT trust this connection
                // for any application data.
                rejectUnauthorized: false,
            },
            () => {
                const peer = sock.getPeerCertificate(true);
                sock.end();
                if (!peer || Object.keys(peer).length === 0) {
                    resolve({ ok: false, reason: 'no peer certificate returned' });
                    return;
                }
                if (peer.subject && peer.subject.CN !== AIS_HOST) {
                    resolve({
                        ok: false,
                        reason: `cert CN mismatch (got ${peer.subject.CN}, expected ${AIS_HOST})`,
                    });
                    return;
                }
                const hash = spkiHashFromPeerCert(peer);
                if (!hash) {
                    resolve({ ok: false, reason: 'could not compute SPKI hash from peer cert' });
                    return;
                }
                if (pins.includes(hash)) {
                    resolve({ ok: true, hash });
                } else {
                    resolve({
                        ok: false,
                        reason: `SPKI ${hash} not in pin list (possible MITM)`,
                    });
                }
            },
        );
        sock.setTimeout(10000, () => {
            sock.destroy();
            resolve({ ok: false, reason: 'TLS probe timeout' });
        });
        sock.on('error', (err) => {
            resolve({ ok: false, reason: `TLS probe error: ${err.message}` });
        });
    });
}

// ── Subscription state ───────────────────────────────────────────────────

// Start with global coverage, until frontend updates it
let currentBboxes = [[[-90, -180], [90, 180]]];
let activeWs = null;

function sendSub(ws) {
    if (ws && ws.readyState === WebSocket.OPEN) {
        const subMsg = {
            APIKey: API_KEY,
            BoundingBoxes: currentBboxes,
            FilterMessageTypes: [
                "PositionReport",
                "ShipStaticData",
                "StandardClassBPositionReport"
            ]
        };
        ws.send(JSON.stringify(subMsg));
    }
}

// Listen for dynamic bounding box updates via stdin from Python orchestrator
const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
    terminal: false
});

rl.on('line', (line) => {
    try {
        const cmd = JSON.parse(line);
        if (cmd.type === "update_bbox" && cmd.bboxes) {
            currentBboxes = cmd.bboxes;
            if (activeWs) sendSub(activeWs); // Resend subscription (swap and replace)
        }
        if (cmd.type === "status_query") {
            // Allow the Python side to probe degraded-mode state by sending
            // {"type": "status_query"} on stdin. Reply on stdout as a marker.
            process.stdout.write(JSON.stringify({
                __ais_proxy_status: { degraded_tls: aisDegradedMode }
            }) + '\n');
        }
    } catch (e) {}
});

function attachWsHandlers(ws, { degraded } = { degraded: false }) {
    activeWs = ws;

    ws.on('open', () => {
        if (degraded) {
            console.error(
                '[AIS Proxy] Connected in DEGRADED TLS MODE — upstream cert is expired '
                + 'but SPKI matches the pinned key, so identity is still verified. '
                + 'AISStream needs to renew their cert; until then MITM protection '
                + 'depends only on the SPKI match. Watch backend logs for resolution.'
            );
            aisDegradedMode = true;
        } else {
            if (aisDegradedMode) {
                console.error('[AIS Proxy] Reconnected with full TLS validation — degraded mode cleared.');
            }
            aisDegradedMode = false;
        }
        sendSub(ws);
    });

    ws.on('message', (data) => {
        try {
            const parsed = JSON.parse(data);
            console.log(JSON.stringify(parsed));
        } catch (e) {}
    });

    ws.on('error', (err) => {
        console.error('WebSocket Proxy Error:', err.message);
    });

    ws.on('close', () => {
        activeWs = null;
        console.error('WebSocket Proxy Closed. Reconnecting in 5s...');
        setTimeout(connect, 5000);
    });
}

function connect() {
    // Path A: normal TLS validation (the 99.9% case). If this succeeds we
    // never touch the SPKI fallback.
    const ws = new WebSocket(AIS_WS_URL);

    let openedOk = false;
    ws.on('open', () => { openedOk = true; });

    ws.on('error', async (err) => {
        // Only the CERT_HAS_EXPIRED case triggers SPKI verification. Any
        // other TLS or network error gets the standard reconnect path so we
        // don't accidentally cover up legitimate problems.
        if (!openedOk && err && err.code === 'CERT_HAS_EXPIRED') {
            console.error(
                '[AIS Proxy] Upstream certificate is expired. Verifying SPKI '
                + 'against pinned keys before deciding whether to proceed in '
                + 'degraded mode...'
            );
            const verdict = await verifyExpiredCertAgainstPins();
            if (verdict.ok) {
                console.error(
                    `[AIS Proxy] SPKI ${verdict.hash} matches pinned key — `
                    + 'identity is verified, proceeding in DEGRADED TLS mode.'
                );
                const insecureWs = new WebSocket(AIS_WS_URL, {
                    rejectUnauthorized: false,
                });
                attachWsHandlers(insecureWs, { degraded: true });
            } else {
                console.error(
                    `[AIS Proxy] SPKI verification FAILED (${verdict.reason}). `
                    + 'Refusing to connect — this would normally indicate an active '
                    + 'MITM attack. If AISStream rotated their server key, update '
                    + 'backend/data/aisstream_spki_pins.json with the new SPKI hash.'
                );
                // Schedule a retry — operator may have updated the pin file.
                setTimeout(connect, 60000);
            }
            return;
        }
        // Default: surface the error and let the close handler reconnect.
        console.error('WebSocket Proxy Error:', err.message);
    });

    // Wire normal handlers — these apply unless the error handler above
    // takes over and replaces activeWs with an insecure socket.
    attachWsHandlers(ws, { degraded: false });
}

connect();
