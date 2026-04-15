import hashlib

from services.mesh.mesh_ibf import IBLT, build_iblt


def _key(seed: str) -> bytes:
    return hashlib.sha256(seed.encode("utf-8")).digest()


def test_iblt_reconcile_diff() -> None:
    keys_a = [_key(f"a{i}") for i in range(20)]
    keys_b = [_key(f"a{i}") for i in range(12)] + [_key(f"b{i}") for i in range(6)]

    iblt_a = build_iblt(keys_a, size=64)
    iblt_b = build_iblt(keys_b, size=64)

    diff = iblt_a.subtract(iblt_b)
    ok, plus, minus = diff.decode()
    assert ok

    plus_set = {p for p in plus}
    minus_set = {m for m in minus}

    assert plus_set == set(keys_a) - set(keys_b)
    assert minus_set == set(keys_b) - set(keys_a)


def test_iblt_compact_roundtrip() -> None:
    keys = [_key(f"x{i}") for i in range(15)]
    iblt = build_iblt(keys, size=64)
    packed = iblt.to_compact_dict()
    iblt2 = IBLT.from_compact_dict(packed)

    diff = iblt.subtract(iblt2)
    ok, plus, minus = diff.decode()
    assert ok
    assert plus == []
    assert minus == []
