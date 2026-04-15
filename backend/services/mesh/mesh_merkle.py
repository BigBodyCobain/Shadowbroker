from __future__ import annotations

import hashlib
from typing import Any


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_leaf(value: str) -> str:
    return _hash_bytes(value.encode("utf-8"))


def hash_pair(left: str, right: str) -> str:
    return _hash_bytes(f"{left}{right}".encode("utf-8"))


def build_merkle_levels(leaves: list[str]) -> list[list[str]]:
    if not leaves:
        return []
    level = [hash_leaf(leaf) for leaf in leaves]
    levels = [level]
    while len(level) > 1:
        next_level: list[str] = []
        for idx in range(0, len(level), 2):
            left = level[idx]
            right = level[idx + 1] if idx + 1 < len(level) else left
            next_level.append(hash_pair(left, right))
        level = next_level
        levels.append(level)
    return levels


def merkle_root(leaves: list[str]) -> str:
    levels = build_merkle_levels(leaves)
    if not levels:
        return ""
    return levels[-1][0]


def merkle_proof_from_levels(levels: list[list[str]], index: int) -> list[dict[str, Any]]:
    if not levels:
        return []
    if index < 0 or index >= len(levels[0]):
        return []
    proof: list[dict[str, Any]] = []
    idx = index
    for level in levels[:-1]:
        is_right = idx % 2 == 1
        sibling_idx = idx - 1 if is_right else idx + 1
        if sibling_idx >= len(level):
            sibling_hash = level[idx]
        else:
            sibling_hash = level[sibling_idx]
        proof.append({"hash": sibling_hash, "side": "left" if is_right else "right"})
        idx //= 2
    return proof


def verify_merkle_proof(
    leaf_value: str, index: int, proof: list[dict[str, Any]], root: str
) -> bool:
    current = hash_leaf(leaf_value)
    idx = index
    for step in proof:
        sibling = str(step.get("hash", ""))
        side = str(step.get("side", "right")).lower()
        if side == "left":
            current = hash_pair(sibling, current)
        else:
            current = hash_pair(current, sibling)
        idx //= 2
    return current == root
