$ErrorActionPreference = "Stop"

$backendRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Push-Location $backendRoot
try {
    $env:PYTHONPATH = "."
    & "C:\Users\vance\AppData\Local\Programs\Python\Python311\python.exe" -m pytest -q `
        tests/mesh/test_privacy_claims.py `
        tests/mesh/test_mesh_endpoint_integrity.py `
        -k "review_surface or review_manifest or review_consistency or explicit_review_export or ordinary_status_omits_explicit_review_surfaces_across_corpus_states"
}
finally {
    Pop-Location
}
