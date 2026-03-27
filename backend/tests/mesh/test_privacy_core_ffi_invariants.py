"""Sprint 1 security-review invariant tests for privacy-core FFI.

These tests exercise the FFI boundary, handle lifecycle, buffer ownership,
and MLS correctness of the Rust privacy-core as accessed through the Python
ctypes bridge.

Test IDs map to the S1 Security Review findings:

  S1-T1  Use-after-release: freed handle must produce error, no ciphertext
  S1-T2  Double-release: second release returns False, no crash
  S1-T3  Public-bundle key-material: exported JSON contains no private key
  S1-T4  MLS round-trip: encrypt → decrypt produces original plaintext
  S1-T5  Removed member cannot decrypt post-removal messages

Requires a compiled privacy-core shared library. If unavailable, tests are
skipped rather than failed.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

# Ensure the backend package is importable.
_backend = Path(__file__).resolve().parents[2]
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

from services.privacy_core_client import (
    PrivacyCoreClient,
    PrivacyCoreError,
    PrivacyCoreUnavailable,
)

_client: PrivacyCoreClient | None = None


def _get_client() -> PrivacyCoreClient:
    """Lazy-load the privacy-core library; skip if unavailable."""
    global _client  # noqa: PLW0603
    if _client is not None:
        return _client
    try:
        _client = PrivacyCoreClient.load()
    except PrivacyCoreUnavailable:
        raise unittest.SkipTest(
            "privacy-core shared library not found — skipping FFI invariant tests"
        )
    return _client


class TestUseAfterRelease(unittest.TestCase):
    """S1-T1: Operations on a released handle must fail cleanly."""

    def test_encrypt_after_release_group(self) -> None:
        """Releasing a group handle then encrypting with it must raise, not encrypt."""
        client = _get_client()

        identity = client.create_identity()
        group = client.create_group(identity)

        # Sanity: encryption works before release.
        ciphertext = client.encrypt_group_message(group, b"pre-release")
        self.assertIsInstance(ciphertext, bytes)
        self.assertGreater(len(ciphertext), 0)

        # Release the group handle.
        released = client.release_group(group)
        self.assertTrue(released)

        # Post-release: must raise, must NOT return ciphertext.
        with self.assertRaises(PrivacyCoreError) as ctx:
            client.encrypt_group_message(group, b"post-release-secret")
        self.assertIn("unknown group handle", str(ctx.exception).lower())

        # Cleanup.
        client.release_identity(identity)

    def test_decrypt_after_release_group(self) -> None:
        """Decrypting with a freed group handle must fail."""
        client = _get_client()

        identity = client.create_identity()
        group = client.create_group(identity)
        ciphertext = client.encrypt_group_message(group, b"test")
        client.release_group(group)

        with self.assertRaises(PrivacyCoreError):
            client.decrypt_group_message(group, ciphertext)

        client.release_identity(identity)


class TestDoubleRelease(unittest.TestCase):
    """S1-T2: Double-releasing a handle must not crash and must return False."""

    def test_double_release_identity(self) -> None:
        client = _get_client()
        identity = client.create_identity()
        first = client.release_identity(identity)
        second = client.release_identity(identity)
        self.assertTrue(first)
        self.assertFalse(second)

    def test_double_release_group(self) -> None:
        client = _get_client()
        identity = client.create_identity()
        group = client.create_group(identity)
        first = client.release_group(group)
        second = client.release_group(group)
        self.assertTrue(first)
        self.assertFalse(second)
        client.release_identity(identity)

    def test_double_release_commit(self) -> None:
        client = _get_client()

        alice = client.create_identity()
        bob = client.create_identity()
        group = client.create_group(alice)
        kp_bytes = client.export_key_package(bob)
        kp_handle = client.import_key_package(kp_bytes)
        commit = client.add_member(group, kp_handle)

        first = client.release_commit(commit)
        second = client.release_commit(commit)
        self.assertTrue(first)
        self.assertFalse(second)

        # Cleanup.
        client.release_group(group)
        client.release_key_package(kp_handle)
        client.release_identity(alice)
        client.release_identity(bob)


class TestPublicBundleNoPrivateKey(unittest.TestCase):
    """S1-T3: Exported public bundle must not contain private key material."""

    def test_bundle_contains_only_public_fields(self) -> None:
        client = _get_client()
        identity = client.create_identity()

        bundle_bytes = client.export_public_bundle(identity)
        bundle = json.loads(bundle_bytes)

        # Expected fields only.
        allowed_keys = {"label", "cipher_suite", "signing_public_key", "credential"}
        self.assertEqual(set(bundle.keys()), allowed_keys)

        # The signing_public_key field must be present and non-empty (it's the PUBLIC key).
        self.assertIsInstance(bundle["signing_public_key"], list)
        self.assertGreater(len(bundle["signing_public_key"]), 0)

        # Verify no field name suggests private material.
        for key in bundle:
            self.assertNotIn("private", key.lower(), f"Field '{key}' suggests private material")
            self.assertNotIn("secret", key.lower(), f"Field '{key}' suggests secret material")

        client.release_identity(identity)

    def test_bundle_for_unknown_identity_fails(self) -> None:
        client = _get_client()
        with self.assertRaises(PrivacyCoreError):
            client.export_public_bundle(0xDEAD)


class TestMLSRoundTrip(unittest.TestCase):
    """S1-T4: Encrypt → decrypt must produce original plaintext."""

    def test_two_member_encrypt_decrypt(self) -> None:
        client = _get_client()

        alice_id = client.create_identity()
        bob_id = client.create_identity()

        # Alice creates a group.
        alice_group = client.create_group(alice_id)

        # Bob exports a key package; Alice imports it and adds Bob.
        kp_bytes = client.export_key_package(bob_id)
        kp_handle = client.import_key_package(kp_bytes)
        commit = client.add_member(alice_group, kp_handle)

        # Get Bob's joined group handle.
        bob_group = client.commit_joined_group_handle(commit)

        # Alice encrypts; Bob decrypts.
        plaintext = b"hello from alice"
        ciphertext = client.encrypt_group_message(alice_group, plaintext)
        self.assertNotEqual(ciphertext, plaintext)

        decrypted = client.decrypt_group_message(bob_group, ciphertext)
        self.assertEqual(decrypted, plaintext)

        # Bob encrypts; Alice decrypts.
        plaintext2 = b"hello from bob"
        ciphertext2 = client.encrypt_group_message(bob_group, plaintext2)
        decrypted2 = client.decrypt_group_message(alice_group, ciphertext2)
        self.assertEqual(decrypted2, plaintext2)

        # Cleanup.
        client.release_commit(commit)
        client.release_key_package(kp_handle)
        client.release_group(alice_group)
        client.release_group(bob_group)
        client.release_identity(alice_id)
        client.release_identity(bob_id)

    def test_old_epoch_ciphertext_fails_after_membership_change(self) -> None:
        client = _get_client()

        alice_id = client.create_identity()
        bob_id = client.create_identity()
        charlie_id = client.create_identity()

        alice_group = client.create_group(alice_id)
        bob_kp = client.export_key_package(bob_id)
        bob_kp_handle = client.import_key_package(bob_kp)
        commit1 = client.add_member(alice_group, bob_kp_handle)
        bob_group = client.commit_joined_group_handle(commit1)

        old_epoch_ct = client.encrypt_group_message(alice_group, b"epoch one")
        self.assertEqual(client.decrypt_group_message(bob_group, old_epoch_ct), b"epoch one")

        charlie_kp = client.export_key_package(charlie_id)
        charlie_kp_handle = client.import_key_package(charlie_kp)
        commit2 = client.add_member(alice_group, charlie_kp_handle)
        charlie_group = client.commit_joined_group_handle(commit2)

        with self.assertRaises(PrivacyCoreError):
            client.decrypt_group_message(alice_group, old_epoch_ct)
        with self.assertRaises(PrivacyCoreError):
            client.decrypt_group_message(bob_group, old_epoch_ct)

        new_epoch_ct = client.encrypt_group_message(alice_group, b"epoch two")
        self.assertEqual(client.decrypt_group_message(charlie_group, new_epoch_ct), b"epoch two")

        for handle in (commit1, commit2):
            client.release_commit(handle)
        for handle in (bob_kp_handle, charlie_kp_handle):
            client.release_key_package(handle)
        for handle in (alice_group, bob_group, charlie_group):
            client.release_group(handle)
        for handle in (alice_id, bob_id, charlie_id):
            client.release_identity(handle)


class TestRemovedMemberCannotDecrypt(unittest.TestCase):
    """S1-T5: A removed member must fail to decrypt post-removal messages."""

    def test_removed_member_decryption_fails(self) -> None:
        client = _get_client()

        alice_id = client.create_identity()
        bob_id = client.create_identity()
        charlie_id = client.create_identity()

        # Alice creates group, adds Bob.
        alice_group = client.create_group(alice_id)
        bob_kp = client.export_key_package(bob_id)
        bob_kp_h = client.import_key_package(bob_kp)
        commit1 = client.add_member(alice_group, bob_kp_h)
        bob_group = client.commit_joined_group_handle(commit1)

        # Alice adds Charlie.
        charlie_kp = client.export_key_package(charlie_id)
        charlie_kp_h = client.import_key_package(charlie_kp)
        commit2 = client.add_member(alice_group, charlie_kp_h)
        charlie_group = client.commit_joined_group_handle(commit2)

        # Verify all three can communicate.
        ct = client.encrypt_group_message(alice_group, b"all three")
        self.assertEqual(client.decrypt_group_message(bob_group, ct), b"all three")

        # Alice removes Bob (member_ref=1, since Alice is 0, Bob is 1).
        # Note: member indices depend on insertion order in mls-rs.
        # We try member_ref=1 for Bob. If it fails we try 2.
        try:
            remove_commit = client.remove_member(alice_group, 1)
        except PrivacyCoreError:
            remove_commit = client.remove_member(alice_group, 2)

        # Post-removal: Alice encrypts a new message.
        post_removal_ct = client.encrypt_group_message(alice_group, b"bob is gone")

        # Charlie should still be able to decrypt.
        post_removal_plain = client.decrypt_group_message(charlie_group, post_removal_ct)
        self.assertEqual(post_removal_plain, b"bob is gone")

        # Bob's group handle should have been removed by the remove_member
        # operation's family cleanup. Attempting to decrypt should fail.
        with self.assertRaises(PrivacyCoreError):
            client.decrypt_group_message(bob_group, post_removal_ct)

        # Cleanup.
        for c in (commit1, commit2, remove_commit):
            client.release_commit(c)
        for kp in (bob_kp_h, charlie_kp_h):
            client.release_key_package(kp)
        for g in (alice_group, charlie_group):
            client.release_group(g)
        for i in (alice_id, bob_id, charlie_id):
            client.release_identity(i)


class TestPrivacyCoreLimits(unittest.TestCase):
    """S7-T5: privacy-core must enforce handle limits and report stats."""

    def test_identity_limit_and_handle_stats(self) -> None:
        client = _get_client()
        client.reset_all_state()
        stats_before = client.handle_stats()
        self.assertEqual(stats_before["identities"], 0)
        self.assertEqual(stats_before["max_identities"], 1024)

        handles = []
        for _ in range(stats_before["max_identities"]):
            handles.append(client.create_identity())

        stats_full = client.handle_stats()
        self.assertEqual(stats_full["identities"], stats_full["max_identities"])

        with self.assertRaises(PrivacyCoreError):
            client.create_identity()

        for handle in handles:
            client.release_identity(handle)


if __name__ == "__main__":
    unittest.main()
