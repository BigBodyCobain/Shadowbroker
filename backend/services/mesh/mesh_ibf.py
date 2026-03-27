from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from typing import Iterable, List, Tuple

KEY_SIZE = 32
DEFAULT_SEEDS = [0x243F6A8885A308D3, 0x13198A2E03707344, 0xA4093822299F31D0]
FINGERPRINT_SEED = 0xC0FFEE1234567890


def _safe_int(val, default=0) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _hash64(data: bytes, seed: int) -> int:
    key = seed.to_bytes(8, "little", signed=False)
    digest = hashlib.blake2b(data, digest_size=8, key=key).digest()
    return int.from_bytes(digest, "little", signed=False)


def _fingerprint(data: bytes) -> int:
    key = FINGERPRINT_SEED.to_bytes(8, "little", signed=False)
    digest = hashlib.blake2b(data, digest_size=8, key=key).digest()
    return int.from_bytes(digest, "little", signed=False)


def _xor_bytes(a: bytes, b: bytes) -> bytes:
    return bytes(x ^ y for x, y in zip(a, b))


def _ensure_key(key: bytes) -> bytes:
    if len(key) != KEY_SIZE:
        raise ValueError(f"IBF key must be {KEY_SIZE} bytes")
    return key


def _b64_encode(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _b64_decode(data: str) -> bytes:
    return base64.b64decode(data.encode("ascii"))


@dataclass
class IBLTCell:
    count: int = 0
    key_xor: bytes = b"\x00" * KEY_SIZE
    hash_xor: int = 0

    def add(self, key: bytes, sign: int) -> None:
        self.count += sign
        self.key_xor = _xor_bytes(self.key_xor, key)
        self.hash_xor ^= _fingerprint(key)


class IBLT:
    def __init__(self, size: int, seeds: List[int] | None = None) -> None:
        if size <= 0:
            raise ValueError("IBLT size must be positive")
        self.size = size
        self.seeds = seeds or list(DEFAULT_SEEDS)
        self.cells: List[IBLTCell] = [IBLTCell() for _ in range(size)]

    def _indexes(self, key: bytes) -> List[int]:
        key = _ensure_key(key)
        return [(_hash64(key, seed) % self.size) for seed in self.seeds]

    def insert(self, key: bytes) -> None:
        key = _ensure_key(key)
        for idx in self._indexes(key):
            self.cells[idx].add(key, 1)

    def delete(self, key: bytes) -> None:
        key = _ensure_key(key)
        for idx in self._indexes(key):
            self.cells[idx].add(key, -1)

    def subtract(self, other: "IBLT") -> "IBLT":
        if self.size != other.size or self.seeds != other.seeds:
            raise ValueError("IBLT mismatch; size or seeds differ")
        out = IBLT(self.size, self.seeds)
        for i, cell in enumerate(self.cells):
            other_cell = other.cells[i]
            out.cells[i] = IBLTCell(
                count=cell.count - other_cell.count,
                key_xor=_xor_bytes(cell.key_xor, other_cell.key_xor),
                hash_xor=cell.hash_xor ^ other_cell.hash_xor,
            )
        return out

    def decode(self) -> Tuple[bool, List[bytes], List[bytes]]:
        plus: List[bytes] = []
        minus: List[bytes] = []
        stack = [i for i, c in enumerate(self.cells) if abs(c.count) == 1]

        while stack:
            idx = stack.pop()
            cell = self.cells[idx]
            if abs(cell.count) != 1:
                continue
            key = cell.key_xor
            if _fingerprint(key) != cell.hash_xor:
                continue
            sign = 1 if cell.count == 1 else -1
            if sign == 1:
                plus.append(key)
            else:
                minus.append(key)
            for j in self._indexes(key):
                if j == idx:
                    continue
                self.cells[j].add(key, -sign)
                if abs(self.cells[j].count) == 1:
                    stack.append(j)
            self.cells[idx] = IBLTCell()

        success = all(
            c.count == 0 and c.hash_xor == 0 and c.key_xor == b"\x00" * KEY_SIZE
            for c in self.cells
        )
        return success, plus, minus

    def to_compact_dict(self) -> dict:
        return {
            "m": self.size,
            "s": self.seeds,
            "c": [[cell.count, _b64_encode(cell.key_xor), cell.hash_xor] for cell in self.cells],
        }

    @classmethod
    def from_compact_dict(cls, data: dict) -> "IBLT":
        size = _safe_int(data.get("m", 0) or 0)
        seeds = data.get("s") or list(DEFAULT_SEEDS)
        cells = data.get("c") or []
        iblt = cls(size, list(seeds))
        if len(cells) != size:
            raise ValueError("IBLT cell count mismatch")
        for i, raw in enumerate(cells):
            count, key_b64, hash_xor = raw
            iblt.cells[i] = IBLTCell(
                count=_safe_int(count, 0),
                key_xor=_b64_decode(str(key_b64)),
                hash_xor=_safe_int(hash_xor, 0),
            )
        return iblt


def build_iblt(keys: Iterable[bytes], size: int) -> IBLT:
    iblt = IBLT(size)
    for key in keys:
        iblt.insert(key)
    return iblt


def minhash_sketch(keys: Iterable[bytes], k: int) -> List[int]:
    if k <= 0:
        return []
    mins: List[int] = []
    for key in keys:
        h = _hash64(key, 0x9E3779B97F4A7C15)
        if len(mins) < k:
            mins.append(h)
            mins.sort()
        elif h < mins[-1]:
            mins[-1] = h
            mins.sort()
    return mins


def minhash_similarity(a: Iterable[int], b: Iterable[int]) -> float:
    a_list = list(a)
    b_list = list(b)
    if not a_list or not b_list:
        return 0.0
    k = min(len(a_list), len(b_list))
    if k <= 0:
        return 0.0
    a_set = set(a_list[:k])
    b_set = set(b_list[:k])
    return len(a_set & b_set) / float(k)
