# Review Surface Closeout

This workstream closes with three accepted explicit review surfaces:

- `explicit_review_export`
- `review_manifest`
- `review_consistency`

They are defended as explicit local-operator/admin-only review surfaces and remain out of ordinary status responses.

## Representative States

The shared review-surface corpus covers these deterministic states:

- `clean_ready`
- `compatibility_debt`
- `operator_override`
- `provenance_gap`

## Regression Entry Point

For a narrow backend-local review-surface regression pass, run:

```powershell
$env:PYTHONPATH='.'
& 'C:\Users\vance\AppData\Local\Programs\Python\Python311\python.exe' -m pytest -q `
  tests/mesh/test_privacy_claims.py `
  tests/mesh/test_mesh_endpoint_integrity.py `
  -k "review_surface or review_manifest or review_consistency or explicit_review_export or ordinary_status_omits_explicit_review_surfaces_across_corpus_states"
```

This selector keeps the review-surface contract freeze and multi-state corpus coverage together without changing the existing backend-local harness shape.
