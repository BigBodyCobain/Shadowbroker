"""Phase 3.3 — Solo-node gate mode.

Pins ``mesh_gate_mls._gate_is_solo`` and the ``solo_pending`` flag that
``compose_encrypted_gate_message`` surfaces in its result.

The hardening is non-hostile: a solo gate (operator + the synthetic
``_reader`` identity, no real peers) still composes and stores messages
normally. The flag tells the caller "this message is sealed but nobody
else can read it until someone joins". Refusing the compose would be the
hostile pattern; surfacing the state is the non-hostile pattern.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class _StubMember:
    """Minimal stand-in for :class:`mesh_gate_mls._GateMemberBinding`.

    The real ``_GateMemberBinding`` carries Rust handles and other state we
    don't need here — :func:`_gate_is_solo` only reads ``label``.
    """

    label: str


@dataclass
class _StubBinding:
    members: dict[str, _StubMember]


def test_phase3_solo_detection_only_operator_returns_solo(monkeypatch):
    """A binding with only the operator's own member (label != _reader)
    must report solo. This is the bare-minimum case before the supervisor
    has minted the synthetic reader identity."""

    from services.mesh import mesh_gate_mls

    binding = _StubBinding(
        members={
            "op-persona": _StubMember(label="operator-label"),
        }
    )
    assert mesh_gate_mls._gate_is_solo(binding) is True


def test_phase3_solo_detection_operator_plus_reader_returns_solo(monkeypatch):
    """The supervisor mints a synthetic ``_reader`` identity so MLS
    encrypt-then-self-decrypt works on a single-operator node. A gate
    with the operator + a single ``_reader`` is still solo — there are
    no real peers to read the message."""

    from services.mesh import mesh_gate_mls

    binding = _StubBinding(
        members={
            "op-persona": _StubMember(label="operator-label"),
            "_reader_abcd1234": _StubMember(label="_reader"),
        }
    )
    assert mesh_gate_mls._gate_is_solo(binding) is True


def test_phase3_solo_detection_two_real_members_returns_not_solo(monkeypatch):
    """As soon as a second non-_reader member is in the binding, the
    gate is no longer solo and the flag flips to False."""

    from services.mesh import mesh_gate_mls

    binding = _StubBinding(
        members={
            "op-persona": _StubMember(label="operator-label"),
            "peer-persona": _StubMember(label="peer-label"),
            "_reader_abcd1234": _StubMember(label="_reader"),
        }
    )
    assert mesh_gate_mls._gate_is_solo(binding) is False


def test_phase3_solo_detection_short_circuits_after_two_real_members(monkeypatch):
    """The detection helper must short-circuit once it has counted two
    real members — useful when a gate has many members and we don't want
    to walk every one. We can't observe the early return directly, but a
    binding with three real members must still be reported as not-solo."""

    from services.mesh import mesh_gate_mls

    binding = _StubBinding(
        members={
            f"member-{i}": _StubMember(label=f"label-{i}")
            for i in range(5)
        }
    )
    binding.members["_reader_xx"] = _StubMember(label="_reader")
    assert mesh_gate_mls._gate_is_solo(binding) is False


def test_phase3_solo_detection_empty_binding_returns_solo(monkeypatch):
    """An empty binding (theoretically impossible but defensive) must
    report solo, not crash."""

    from services.mesh import mesh_gate_mls

    binding = _StubBinding(members={})
    assert mesh_gate_mls._gate_is_solo(binding) is True


def test_phase3_solo_detection_only_reader_returns_solo(monkeypatch):
    """If the only member is a synthetic ``_reader`` (an edge case where
    the operator has no active gate persona), the gate is solo: zero
    real members."""

    from services.mesh import mesh_gate_mls

    binding = _StubBinding(
        members={
            "_reader_xx": _StubMember(label="_reader"),
        }
    )
    assert mesh_gate_mls._gate_is_solo(binding) is True
