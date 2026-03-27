"""Wormhole-backed DM ratchet state and crypto.

This is the first DM custody move out of the browser. When Wormhole is active,
the frontend no longer persists ratchet/session state in IndexedDB; instead the
agent owns the session records and performs ratchet encrypt/decrypt operations
locally on behalf of the UI.
"""

from __future__ import annotations

import base64
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import hashes, hmac
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, PublicFormat, NoEncryption

from services.mesh.mesh_wormhole_identity import bootstrap_wormhole_identity, read_wormhole_identity
from services.mesh.mesh_secure_storage import read_secure_json, write_secure_json

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
STATE_FILE = DATA_DIR / "wormhole_dm_ratchet.json"
STATE_LOCK = threading.RLock()

MAX_SKIP = 32
PAD_BUCKET = 1024
PAD_STEP = 512
PAD_MAX = 4096
PAD_MAGIC = "SBP1"


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _unb64(data: str | bytes | None) -> bytes:
    if not data:
        return b""
    if isinstance(data, bytes):
        return base64.b64decode(data)
    return base64.b64decode(data.encode("ascii"))


def _zero_bytes(length: int) -> bytes:
    return bytes([0] * length)


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _header_aad(header: dict[str, Any]) -> bytes:
    return _stable_json(header).encode("utf-8")


def _build_padded_payload(plaintext: str) -> bytes:
    data = plaintext.encode("utf-8")
    length = len(data)
    target = PAD_BUCKET
    if length + 6 > target:
        target = ((length + 6 + PAD_STEP - 1) // PAD_STEP) * PAD_STEP
    if target > PAD_MAX:
        target = ((length + 6 + PAD_STEP - 1) // PAD_STEP) * PAD_STEP
    out = bytearray(target)
    out[0:4] = PAD_MAGIC.encode("utf-8")
    out[4] = (length >> 8) & 0xFF
    out[5] = length & 0xFF
    out[6 : 6 + length] = data
    if target > length + 6:
        out[6 + length :] = os.urandom(target - (6 + length))
    return bytes(out)


def _unpad_payload(data: bytes) -> str:
    if len(data) < 6:
        return data.decode("utf-8", errors="replace")
    magic = data[:4].decode("utf-8", errors="ignore")
    if magic != PAD_MAGIC:
        return data.decode("utf-8", errors="replace")
    length = (data[4] << 8) + data[5]
    if length <= 0 or 6 + length > len(data):
        return data.decode("utf-8", errors="replace")
    return data[6 : 6 + length].decode("utf-8", errors="replace")


def _load_all_states() -> dict[str, dict[str, Any]]:
    with STATE_LOCK:
        try:
            raw = read_secure_json(STATE_FILE, lambda: {})
        except Exception:
            import logging
            logging.getLogger(__name__).warning(
                "Wormhole ratchet state could not be decrypted — starting fresh"
            )
            STATE_FILE.unlink(missing_ok=True)
            raw = {}
        if not isinstance(raw, dict):
            return {}
        return {str(k): dict(v) for k, v in raw.items() if isinstance(v, dict)}


def _save_all_states(states: dict[str, dict[str, Any]]) -> None:
    with STATE_LOCK:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        write_secure_json(STATE_FILE, states)


def _get_state(peer_id: str) -> dict[str, Any] | None:
    return _load_all_states().get(peer_id)


def _set_state(peer_id: str, state: dict[str, Any]) -> None:
    states = _load_all_states()
    states[peer_id] = state
    _save_all_states(states)


def reset_wormhole_dm_ratchet(peer_id: str | None = None) -> dict[str, Any]:
    if peer_id:
        states = _load_all_states()
        states.pop(peer_id, None)
        _save_all_states(states)
    else:
        _save_all_states({})
    return {"ok": True, "peer_id": peer_id or "", "cleared_all": not bool(peer_id)}


def _generate_ratchet_key_pair() -> dict[str, str]:
    priv = x25519.X25519PrivateKey.generate()
    priv_raw = priv.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    pub_raw = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return {
        "pub": _b64(pub_raw),
        "priv": _b64(priv_raw),
        "algo": "X25519",
    }


def _derive_dh_secret(priv_b64: str, their_pub_b64: str) -> bytes:
    priv = x25519.X25519PrivateKey.from_private_bytes(_unb64(priv_b64))
    pub = x25519.X25519PublicKey.from_public_bytes(_unb64(their_pub_b64))
    return priv.exchange(pub)


def _wormhole_long_term_dh_priv_b64() -> str:
    data = read_wormhole_identity()
    if not data.get("bootstrapped") or not data.get("dh_private_key"):
        bootstrap_wormhole_identity()
        data = read_wormhole_identity()
    return str(data.get("dh_private_key", "") or "")


def _hkdf(ikm: bytes, salt: bytes, info: str, length: int) -> bytes:
    derived = HKDF(
        algorithm=hashes.SHA256(),
        length=length,
        salt=salt,
        info=info.encode("utf-8"),
    ).derive(ikm)
    return bytes(derived)


def _kdf_rk(rk: bytes, dh_out: bytes) -> tuple[bytes, bytes]:
    salt = rk if rk else _zero_bytes(32)
    out = _hkdf(dh_out, salt, "SB-DR-RK", 64)
    return out[:32], out[32:64]


def _hmac_sha256(key_bytes: bytes, data: bytes) -> bytes:
    mac = hmac.HMAC(key_bytes, hashes.SHA256())
    mac.update(data)
    return bytes(mac.finalize())


def _kdf_ck(ck: bytes) -> tuple[bytes, bytes]:
    mk = _hmac_sha256(ck, b"\x01")
    next_ck = _hmac_sha256(ck, b"\x02")
    return next_ck, mk


def _aes_gcm_encrypt(mk: bytes, plaintext: str, aad: bytes) -> str:
    iv = os.urandom(12)
    aes = AESGCM(mk)
    encoded = _build_padded_payload(plaintext)
    ciphertext = aes.encrypt(iv, encoded, aad)
    return _b64(iv + ciphertext)


def _aes_gcm_decrypt(mk: bytes, ciphertext_b64: str, aad: bytes) -> str:
    combined = _unb64(ciphertext_b64)
    iv = combined[:12]
    ciphertext = combined[12:]
    aes = AESGCM(mk)
    plaintext = aes.decrypt(iv, ciphertext, aad)
    return _unpad_payload(bytes(plaintext))


def _skip_message_keys(state: dict[str, Any], until: int) -> None:
    if not state.get("ckr"):
        return
    skipped = dict(state.get("skipped") or {})
    while int(state.get("nr", 0) or 0) < until:
        next_ck, mk = _kdf_ck(_unb64(str(state["ckr"])))
        key_id = f"{state.get('dhRemote', '')}:{int(state.get('nr', 0) or 0)}"
        if len(skipped) < MAX_SKIP:
            skipped[key_id] = _b64(mk)
        state["ckr"] = _b64(next_ck)
        state["nr"] = int(state.get("nr", 0) or 0) + 1
    state["skipped"] = skipped


def _dh_ratchet(state: dict[str, Any], remote_dh: str, pn: int) -> dict[str, Any]:
    _skip_message_keys(state, pn)
    state["pn"] = int(state.get("ns", 0) or 0)
    state["ns"] = 0
    state["nr"] = 0
    state["dhRemote"] = remote_dh

    rk_bytes = _unb64(str(state.get("rk", "") or "")) or _zero_bytes(32)
    dh_out_1 = _derive_dh_secret(str(state.get("dhSelfPriv", "")), str(state.get("dhRemote", "")))
    rk_1, ck_r = _kdf_rk(rk_bytes, dh_out_1)
    state["rk"] = _b64(rk_1)
    state["ckr"] = _b64(ck_r)

    fresh = _generate_ratchet_key_pair()
    state["dhSelfPub"] = fresh["pub"]
    state["dhSelfPriv"] = fresh["priv"]
    dh_out_2 = _derive_dh_secret(str(state.get("dhSelfPriv", "")), str(state.get("dhRemote", "")))
    rk_2, ck_s = _kdf_rk(_unb64(str(state.get("rk", ""))), dh_out_2)
    state["rk"] = _b64(rk_2)
    state["cks"] = _b64(ck_s)
    state["algo"] = "X25519"
    state["updated"] = int(time.time() * 1000)
    return state


def _init_sender_state(peer_id: str, their_dh_pub: str) -> dict[str, Any]:
    fresh = _generate_ratchet_key_pair()
    dh_out = _derive_dh_secret(fresh["priv"], their_dh_pub)
    rk, ck = _kdf_rk(_zero_bytes(32), dh_out)
    return {
        "algo": "X25519",
        "rk": _b64(rk),
        "cks": _b64(ck),
        "ckr": "",
        "dhSelfPub": fresh["pub"],
        "dhSelfPriv": fresh["priv"],
        "dhRemote": their_dh_pub,
        "ns": 0,
        "nr": 0,
        "pn": 0,
        "skipped": {},
        "updated": int(time.time() * 1000),
    }


def _init_receiver_state(peer_id: str, sender_dh_pub: str) -> dict[str, Any]:
    long_term_priv = _wormhole_long_term_dh_priv_b64()
    if not long_term_priv:
        raise ValueError("missing_long_term_key")
    dh_out = _derive_dh_secret(long_term_priv, sender_dh_pub)
    rk, ck = _kdf_rk(_zero_bytes(32), dh_out)
    fresh = _generate_ratchet_key_pair()
    return {
        "algo": "X25519",
        "rk": _b64(rk),
        "cks": "",
        "ckr": _b64(ck),
        "dhSelfPub": fresh["pub"],
        "dhSelfPriv": fresh["priv"],
        "dhRemote": sender_dh_pub,
        "ns": 0,
        "nr": 0,
        "pn": 0,
        "skipped": {},
        "updated": int(time.time() * 1000),
    }


def _ensure_send_chain(state: dict[str, Any]) -> dict[str, Any]:
    if state.get("cks"):
        return state
    rk_bytes = _unb64(str(state.get("rk", "") or "")) or _zero_bytes(32)
    dh_out = _derive_dh_secret(str(state.get("dhSelfPriv", "")), str(state.get("dhRemote", "")))
    rk, ck = _kdf_rk(rk_bytes, dh_out)
    state["rk"] = _b64(rk)
    state["cks"] = _b64(ck)
    state["updated"] = int(time.time() * 1000)
    return state


def encrypt_wormhole_dm(peer_id: str, peer_dh_pub: str, plaintext: str) -> dict[str, Any]:
    if not peer_id or not peer_dh_pub:
        return {"ok": False, "detail": "peer_id and peer_dh_pub are required"}
    state = _get_state(peer_id)
    if not state:
        state = _init_sender_state(peer_id, peer_dh_pub)
    state = _ensure_send_chain(state)
    next_ck, mk = _kdf_ck(_unb64(str(state.get("cks", ""))))
    n = int(state.get("ns", 0) or 0)
    state["ns"] = n + 1
    state["cks"] = _b64(next_ck)
    header = {
        "v": 2,
        "dh": str(state.get("dhSelfPub", "")),
        "pn": int(state.get("pn", 0) or 0),
        "n": n,
        "alg": "X25519",
    }
    ct = _aes_gcm_encrypt(mk, plaintext, _header_aad(header))
    wrapped = _b64(_stable_json({"h": header, "ct": ct}).encode("utf-8"))
    state["updated"] = int(time.time() * 1000)
    _set_state(peer_id, state)
    return {"ok": True, "result": f"dr2:{wrapped}"}


def decrypt_wormhole_dm(peer_id: str, ciphertext: str) -> dict[str, Any]:
    if not ciphertext.startswith("dr2:"):
        return {"ok": False, "detail": "legacy"}
    try:
        raw = ciphertext[4:]
        payload = json.loads(_unb64(raw).decode("utf-8"))
        header = dict(payload.get("h") or {})
        ct = str(payload.get("ct") or "")
        remote_dh = str(header.get("dh") or "")
        pn = int(header.get("pn", 0) or 0)
        n = int(header.get("n", 0) or 0)

        state = _get_state(peer_id)
        if not state:
            state = _init_receiver_state(peer_id, remote_dh)

        if remote_dh and remote_dh != str(state.get("dhRemote", "")):
            state = _dh_ratchet(state, remote_dh, pn)

        skipped = dict(state.get("skipped") or {})
        skip_key = f"{remote_dh}:{n}"
        if skip_key in skipped:
            mk = _unb64(skipped.pop(skip_key))
            state["skipped"] = skipped
            _set_state(peer_id, state)
            return {"ok": True, "result": _aes_gcm_decrypt(mk, ct, _header_aad(header))}

        _skip_message_keys(state, n)
        if not state.get("ckr"):
            return {"ok": False, "detail": "no_receive_chain"}
        next_ck, mk = _kdf_ck(_unb64(str(state.get("ckr", ""))))
        state["ckr"] = _b64(next_ck)
        state["nr"] = int(state.get("nr", 0) or 0) + 1
        state["updated"] = int(time.time() * 1000)
        _set_state(peer_id, state)
        return {"ok": True, "result": _aes_gcm_decrypt(mk, ct, _header_aad(header))}
    except Exception as exc:
        return {"ok": False, "detail": str(exc) or "ratchet_decrypt_failed"}
