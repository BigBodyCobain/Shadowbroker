$ErrorActionPreference = "Stop"

$backendRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Push-Location $backendRoot
try {
    $env:PYTHONPATH = "."
    python -m pytest -q `
        tests/mesh/test_private_adversarial_regression.py `
        tests/mesh/test_privacy_claims.py `
        tests/mesh/test_signed_write_decorator.py `
        tests/mesh/test_phase6_protocol_context.py `
        tests/mesh/test_signed_write_transport_matrix.py `
        tests/mesh/test_private_dispatcher.py `
        tests/mesh/test_private_release_outbox.py `
        tests/mesh/test_mesh_relay_policy.py `
        tests/mesh/test_gate_legacy_migration.py `
        tests/mesh/test_gate_rns_envelope_distribution.py
}
finally {
    Pop-Location
}
