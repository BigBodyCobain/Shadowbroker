# Desktop Release Guide

This directory now has a repeatable desktop release path with branded bundle
icons, checksum output, Tauri updater artifacts, and a local updater signing
key path, but **not** full Windows/macOS distribution signing/notarization.

## Entry points

Use any of these:

```bash
# POSIX shell
./build.sh

# Windows PowerShell
./build.ps1

# Cross-platform npm wrapper
npm --prefix desktop-shell run build:desktop
```

Use `--clean` when you want to wipe the previous static export, companion
bundle, managed backend bundle, generated icons, and old installer outputs
before rebuilding.

Prerequisites:

- Rust toolchain
- `cargo tauri` available via `cargo install tauri-cli@^2`
- Node.js / npm with the frontend dependencies already installed

## CI / GitHub Actions

The repo also has a desktop matrix workflow at:

```text
.github/workflows/desktop-release.yml
```

What it does today:

- builds unsigned desktop artifacts on Windows, macOS, and Linux
- uploads bundle artifacts for PRs and branch builds
- on `v*.*.*` tags, attaches release assets to the GitHub release
- forwards Apple signing/notarization secrets to the macOS build **if** they
  exist, but does not require them

See [RELEASE_INPUTS.md](./RELEASE_INPUTS.md) for the plain-language answer to
"what would I need later?".

## What the build does

1. Generates the desktop icon set in `src-tauri/icons/`
2. Stages a desktop-only frontend export tree that omits Next server-only
   routes/middleware (`src/app/api`, `src/middleware.ts`)
3. Stages a managed backend runtime bundle into `src-tauri/backend-runtime/`
4. Builds the frontend export with `NEXT_OUTPUT=export`
5. Copies `frontend/out` into `src-tauri/companion-www/`
6. Runs `cargo tauri build`
7. Writes:
   - `src-tauri/target/release/bundle/SHA256SUMS.txt`
   - `src-tauri/target/release/bundle/release-manifest.json`
   - `src-tauri/target/release/bundle/latest.json` when signed updater
     artifacts are present

For CI/release builds, the backend release-gate attestation is also staged into
the managed backend bundle at `backend-runtime/data/release_attestation.json`,
and the managed-backend updater refreshes that file on version sync without
overwriting the rest of the runtime `data/` directory.

## Release artifacts

Artifacts are emitted under:

```text
desktop-shell/tauri-skeleton/src-tauri/target/release/bundle/
```

Expected bundle types vary by platform:

- Windows: `.msi`, `.exe`
- macOS: `.dmg`, `.app`-related archives
- Linux: `.deb`, `.AppImage`

## What is still manual

- Windows code signing
- macOS notarization/signing credentials
- Publishing `latest.json` plus the signed updater installer assets to the
  GitHub release
- Final splash/installer copy polish

## Tauri updater notes

The updater public key is baked into `src-tauri/tauri.conf.json`. Keep the
private key in `release-secrets/shadowbroker-updater.key` and its local
password file in `release-secrets/shadowbroker-updater.key.pass`, or provide
the same values through `TAURI_SIGNING_PRIVATE_KEY` and
`TAURI_SIGNING_PRIVATE_KEY_PASSWORD` at build time. The local
`release-secrets/` folder is gitignored.

The production updater endpoint is:

```text
https://github.com/BigBodyCobain/Shadowbroker/releases/latest/download/latest.json
```

For GitHub releases, upload `latest.json`, the installer (`.msi` / `.exe`), and
the matching `.sig` files generated under `src-tauri/target/release/bundle/`.
Tauri updater signing verifies update packages only; it does not remove Windows
SmartScreen warnings. Windows public trust still requires a real code-signing
certificate later.

## Trust model reminder

The packaged build still uses:

- a bundled local backend runtime that the desktop app owns by default
- Rust-authoritative policy enforcement for privileged local control
- the packaged loopback app server for same-origin non-privileged `/api/*`
- reduced-trust browser companion mode with no native bridge injection
