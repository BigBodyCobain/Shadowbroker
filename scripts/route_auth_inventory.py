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
    deps = []
    for hint in ['require_admin', 'require_local_operator', 'require_openclaw_or_local', 'require_scoped', 'require_peer', 'operator_origin_allowed']:
        if hint in block:
            deps.append(hint)
    if 'Depends(require_admin)' in block or 'require_admin' in block:
        return 'admin/scoped'
    if 'require_local_operator' in block:
        return 'local-operator'
    if 'require_openclaw_or_local' in block:
        return 'openclaw-or-local'
    if 'require_peer' in block:
        return 'peer-hmac'
    if 'Depends(' in block:
        return 'depends-other'
    return 'UNCLASSIFIED'


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
            block = '\n'.join(block_lines)
            m = ROUTE_RE.search(block)
            if m:
                method = m.group(1).upper()
                arg = m.group(2).strip().split(',')[0].strip().strip('"\'')
                dm = re.search(r"(?:async def|def)\s+([A-Za-z0-9_]+)", block)
                name = dm.group(1) if dm else '?'
                cls = classify(block)
                if cls == 'UNCLASSIFIED' and default_auth != 'UNCLASSIFIED':
                    cls = default_auth + ' (router-default)'
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
        f.write(f'- Files scanned: {1 + len(ROUTER_FILES)}\n')
        f.write(f'- Routes found: {len(rows)}\n')
        f.write(f'- UNCLASSIFIED: {len(unclassified)}\n\n')
        f.write('| Method | Path | Handler | Auth classification | File |\n')
        f.write('|---|---|---|---|---|\n')
        for m, path, name, cls, file in rows:
            f.write(f'| {m} | `{path}` | `{name}` | {cls} | `{file}` |\n')
    print(f'wrote {OUT} routes={len(rows)} unclassified={len(unclassified)}')

if __name__ == '__main__':
    main()
