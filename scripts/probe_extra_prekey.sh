#!/usr/bin/env bash
set -euo pipefail
AK="$(docker exec shadowbroker-backend printenv ADMIN_KEY)"
INV="$(curl -s -H "X-Admin-Key: ${AK}" "http://127.0.0.1:8000/api/wormhole/dm/invite?label=probe")"
echo "invite=${INV:0:200}"
HANDLE="$(python3 -c 'import json,sys; d=json.load(sys.stdin); print((d.get("invite") or {}).get("payload", {}).get("prekey_lookup_handle", ""))' <<<"${INV}")"
echo "handle=${HANDLE}"
curl -s "http://127.0.0.1:8000/api/mesh/dm/prekey-bundle?lookup_token=${HANDLE}" | head -c 400
echo
