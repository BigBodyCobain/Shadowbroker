# Contributor Map

ShadowBroker is a monorepo. The fastest way to contribute is to pick one
surface, keep the change small, and run the matching test slice before opening
a pull request.

## Main Areas

| Area | Path | Stack | Start here when |
| --- | --- | --- | --- |
| Web dashboard | `frontend/` | Next.js, React, MapLibre | Changing UI behavior, map layers, panels, client-side API code, or tests |
| Backend API | `backend/` | FastAPI, Python | Changing API routes, data shaping, local auth gates, or feed orchestration |
| Desktop app | `desktop-shell/` | Tauri, TypeScript, Rust | Changing packaged desktop runtime behavior or native bridge code |
| Privacy core | `privacy-core/` | Rust | Changing low-level cryptographic or privacy primitives |
| Deployment | `docker-compose*.yml`, `helm/`, `.github/` | Docker, Helm, GitHub Actions | Changing packaging, CI, images, or cluster deployment |
| Agent package | `openclaw-skills/` | Python skill package | Changing OpenClaw/agent integration helpers |

## Low-Risk First Contributions

- Documentation fixes that make setup, architecture, or operations clearer.
- Small frontend utilities with focused tests under `frontend/src/__tests__/`.
- Isolated UI components outside the large map shell.
- Version or metadata consistency fixes across package manifests.
- Backend tests that document existing behavior without changing live-data paths.

## Areas That Need Extra Care

These paths are security-sensitive or operationally sensitive and have explicit
owners in `.github/CODEOWNERS`:

- `backend/auth.py`
- `backend/services/mesh/`
- `backend/services/fetchers/`
- `.github/workflows/`
- Docker Compose, Helm, and CI/deploy files
- `frontend/src/i18n/`

Changes there are welcome, but expect stricter review and a stronger test plan.

## Large Files To Avoid For First PRs

Some files are intentionally central and carry a lot of historical behavior.
Avoid broad edits in these until you have a narrow bug or test target:

- `frontend/src/components/MaplibreViewer.tsx`
- `frontend/src/components/MeshTerminal.tsx`
- `frontend/src/components/SettingsPanel.tsx`
- `frontend/src/components/NewsFeed.tsx`
- `backend/main.py`
- `backend/routers/ai_intel.py`
- `backend/routers/mesh_public.py`

Prefer extracting or testing a small behavior around them instead of rewriting
the file.

## Test Slices

Run the smallest relevant check locally, then expand if the change touches a
shared contract.

```bash
# Backend targeted tests
(cd backend && uv sync --frozen --group dev)
(cd backend && uv run pytest tests/path/to_test.py -q)

# Frontend targeted tests
(cd frontend && npm ci)
(cd frontend && npx vitest run src/__tests__/path/to_test.ts)

# Full PR checks from CONTRIBUTING.md
pytest backend/tests/
(cd frontend && npx vitest run)
```

If a change touches live-data APIs, fetchers, or unattended deployments, also
review `docs/production-hardening.md` and note the result in the PR template.
