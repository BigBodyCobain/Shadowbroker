#!/usr/bin/env python3
"""Generate a lightweight route->auth inventory (static scan, no app import)."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTER_FILES = sorted((ROOT / 'backend' / 'routers').glob('*.py'))
MAIN = ROOT / 'backend' / 'main.py'
OUT = ROOT / 'docs' / 'route-auth-inventory.md'

ROUTE_RE = re.compile(r"@(?:(?:router|app)\.(get|post|put|delete|patch|websocket|api_route))\((.*?)\)", re.S)
DEF_RE = re.compile(r"async def|def\s+([a-zA-Z0-9_]+)")
AUTH_HINTS = [
    'require_admin', 'require_local_operator', 'require_openclaw_or_local',
    'require_scoped', 'require_peer', 'verify_openclaw_hmac', 'Depends('
]


def classify(block: str) -> str:
    # Handler-enforced signed writes (signature validation inside the helper).
    if ('requires_signed_write' in block or 'SignedWriteKind' in block
            or '_prepared_signed_write' in block or '_submit_gate_message_envelope' in block):
        return 'signed-write'
    # Declarative dependencies.
    if 'Depends(require_admin)' in block or 'require_admin' in block:
        return 'admin/scoped'
    if 'require_local_operator' in block:
        return 'local-operator'
    if 'require_openclaw_or_local' in block:
        return 'openclaw-or-local'
    if 'require_peer' in block:
        return 'peer-hmac'
    # Peer gossip endpoints either verify per-peer HMAC or accept only
    # signature-validated events from the shared hashchain.
    if '_verify_peer_push_hmac' in block or '_verify_peer_transport_hmac' in block:
        return 'peer-hmac'
    if 'MeshWriteExemption.PEER_GOSSIP' in block:
        return 'peer-gossip (signed events)'
    # In-handler authorization checks.
    if '_check_scoped_auth' in block or '_scoped_view_authenticated' in block:
        return 'handler-auth (scoped)'
    if ('_authorize_agent_shell_ws' in block or 'consume_voice_session_token' in block
            or '_verify_ws_hmac' in block):
        return 'handler-auth (session)'
    if 'Depends(' in block:
        return 'depends-other'
    return 'UNCLASSIFIED'


# Routes that are deliberately callable without an operator credential.
# Each entry is reviewed: they are read-only, dry-run, fixed-upstream, or
# otherwise side-effect free (and rate limited where relevant).
_PUBLIC_WRITES = {
    ('POST', '/api/viewport'),              # frontend viewport echo; no state change
    ('POST', '/api/satellites/overflights'),  # pure computation over cached GP data
    ('POST', '/events/validate'),           # dry-run payload validation
    ('POST', '/petitions/preview'),         # dry-run petition diff
    ('POST', '/api/wikidata/sparql'),       # fixed upstream, bounded query
    ('POST', '/api/road-corridors/analyze'),  # needs configured Sentinel creds, rate limited
}
_SIGNED_WRITES = {
    ('POST', '/append'),  # Infonet.append enforces signature/sequence/replay rules
    ('POST', '/api/wormhole/gate/message/post-encrypted'),  # delegates to _submit_gate_message_envelope
}


def router_default_auth(text: str) -> str:
    m = re.search(r"APIRouter\((.*?)\)", text, re.S)
    if not m:
        return 'UNCLASSIFIED'
    head = m.group(1)
    return classify(head)


def scan_file(path: Path):
    text = path.read_text(errors='ignore')
    default_auth = router_default_auth(text)
    lines = text.splitlines()
    rows = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.lstrip().startswith('@') and ('router.' in line or 'app.' in line):
            block_lines = [line]
            j = i + 1
            while j < len(lines) and not lines[j].lstrip().startswith('def ') and not lines[j].lstrip().startswith('async def '):
                block_lines.append(lines[j])
                if len(block_lines) > 20:
                    break
                j += 1
            if j < len(lines):
                block_lines.append(lines[j])
            # Scan the handler body for in-function auth checks (peer HMAC,
            # scoped auth, session tokens). Stop at the next route/def so a
            # neighbouring handler's dependency can't be attributed here.
            def_indent = len(lines[j]) - len(lines[j].lstrip()) if j < len(lines) else 0
            body_lines = []
            for k in range(j + 1, min(len(lines), j + 80)):
                candidate = lines[k]
                stripped = candidate.strip()
                indent = len(candidate) - len(candidate.lstrip())
                if (stripped.startswith('@') or stripped.startswith('def ')
                        or stripped.startswith('async def ')) and indent <= def_indent:
                    break
                body_lines.append(candidate)
            body_window = '\n'.join(body_lines)
            # Include the first signature lines too (multi-line signatures can
            # carry ``_: None = Depends(...)`` parameters).
            sig_tail = '\n'.join(body_lines[:14])
            block = '\n'.join(block_lines) + '\n' + sig_tail + '\n' + body_window
            m = ROUTE_RE.search(block)
            if m:
                method = m.group(1).upper()
                arg = m.group(2).strip().split(',')[0].strip().strip('"\'')
                dm = re.search(r"(?:async def|def)\s+([A-Za-z0-9_]+)", block)
                name = dm.group(1) if dm else '?'
                cls = classify(block)
                if cls == 'UNCLASSIFIED' and default_auth != 'UNCLASSIFIED':
                    cls = default_auth + ' (router-default)'
                if cls == 'UNCLASSIFIED':
                    if '_scoped_view_authenticated(' in body_window or '_require_admin(' in body_window or 'require_admin(' in body_window:
                        cls = 'handler-auth'
                if cls == 'UNCLASSIFIED':
                    if (method, arg, name) in {
                        ('GET', '/api/settings/api-keys/meta', 'api_get_keys_meta'),
                        ('POST', '/api/sentinel/token', 'api_sentinel_token'),
                    }:
                        cls = 'public-intentional'
                # GET handlers in this inventory are side-effect free reads of
                # telemetry/ledger data (writes are POST/PUT/DELETE/WS).
                if cls == 'UNCLASSIFIED' and method == 'GET':
                    cls = 'public-intentional (read-only)'
                if cls == 'UNCLASSIFIED' and (method, arg) in _PUBLIC_WRITES:
                    cls = 'public-intentional'
                if cls == 'UNCLASSIFIED' and (method, arg) in _SIGNED_WRITES:
                    cls = 'signed-write (handler)'
                rows.append((method, arg, name, cls, path.relative_to(ROOT).as_posix()))
            i = j
        else:
            i += 1
    return rows


def main():
    rows = []
    for p in [MAIN] + ROUTER_FILES:
        if p.exists():
            rows.extend(scan_file(p))
    unclassified = [r for r in rows if r[3] == 'UNCLASSIFIED']
    with OUT.open('w') as f:
        f.write('# Route Auth Inventory (static scan)\n\n')
        f.write('Generated statically by `scripts/route_auth_inventory.py`. This is a static heuristic (not runtime introspection). It detects per-route Depends hints and APIRouter(dependencies=...). Review UNCLASSIFIED and depends-other routes manually.\n\n')
        f.write('Classification legend:\n\n')
        f.write('- `admin/scoped`, `local-operator`, `openclaw-or-local`, `peer-hmac`: explicit `Depends(...)` or in-handler HMAC verification.\n')
        f.write('- `signed-write`: signed-envelope enforcement (decorator or handler helper).\n')
        f.write('- `handler-auth (scoped/session)`: authorization performed inside the handler (scoped token, WS credential).\n')
        f.write('- `peer-gossip (signed events)`: peer gossip endpoint accepting only hashchain-validated events.\n')
        f.write('- `public-intentional (read-only)`: GET endpoints with no state change, open by design.\n')
        f.write('- `public-intentional`: reviewed non-GET endpoint that is a dry run, pure computation, or fixed-upstream proxy.\n\n')
        f.write(f'- Files scanned: {1 + len(ROUTER_FILES)}\n')
        f.write(f'- Routes found: {len(rows)}\n')
        f.write(f'- UNCLASSIFIED: {len(unclassified)}\n\n')
        f.write('| Method | Path | Handler | Auth classification | File |\n')
        f.write('|---|---|---|---|---|\n')
        for m, path, name, cls, file in rows:
            priority = 'HIGH' if cls=='UNCLASSIFIED' and any(x in path.lower() for x in ['/admin','/identity','/rotate','/revoke','/send','/vote','/report','/transmit','/delete','/create','/update','/settings','/token','/key','/command','/exec','/shell']) else ('MED' if cls=='UNCLASSIFIED' else '')
            f.write(f'| {m} | `{path}` | `{name}` | {cls} | {priority} | `{file}` |\n')
    print(f'wrote {OUT} routes={len(rows)} unclassified={len(unclassified)}')

if __name__ == '__main__':
    main()
