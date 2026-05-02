# Desktop Shell

Native-side scaffold for the ShadowBroker desktop boundary.

## Purpose

This package owns the accepted desktop track:

- native privileged control routing through Rust
- authoritative policy enforcement and audit
- packaged managed local backend ownership
- packaged desktop runtime with same-origin `/api/*`
- tray/menu-bar lifecycle
- optional reduced-trust browser companion mode
- desktop packaging/release tooling

Browser mode remains intact; the desktop path layers on top of it.

## Source of truth

The shared desktop control contract still lives in:

- `frontend/src/lib/desktopControlContract.ts`
- `frontend/src/lib/desktopControlRouting.ts`

The native side imports that contract instead of redefining it.

## Layout

```text
desktop-shell/
├── package.json
├── scripts/
│   └── run-desktop-build.cjs          # Cross-platform npm build wrapper
├── src/
│   ├── runtimeBridge.ts
│   ├── nativeControlRouter.ts
│   ├── nativeControlAudit.ts
│   └── handlers/
└── tauri-skeleton/
    ├── dev.sh
    ├── build.sh
    ├── build.ps1
    ├── RELEASE.md
    ├── scripts/
    │   ├── generate-icons.cjs
    │   └── write-release-manifest.cjs
    └── src-tauri/
        ├── Cargo.toml
        ├── tauri.conf.json
        ├── icons/                      # Generated branded bundle assets
        └── src/
            ├── main.rs
            ├── bridge.rs
            ├── policy.rs
            ├── tray.rs
            ├── companion.rs
            ├── companion_server.rs
            ├── handlers.rs
            └── http_client.rs
```

## Desktop runtime model

### Native privileged path

The accepted 27-command privileged path remains native-only:

- frontend bridge detection builds `window.__SHADOWBROKER_LOCAL_CONTROL__`
- privileged requests go through Tauri IPC
- Rust policy enforces capability/profile rules before dispatch
- Rust audit ring records all outcomes
- the native admin key never reaches webview JavaScript

### Packaged main window

Packaged builds now own a bundled local backend runtime by default, then use an
app-level loopback server as the native window origin so ordinary
non-privileged `/api/*` fetches resolve same-origin instead of dying on static
asset serving.

### Browser companion

Browser companion remains:

- optional
- loopback-only
- explicitly enabled
- reduced-trust

It never receives the native bridge injection, and it is not a drop-in
replacement for standalone browser mode.

## Packaging / release flow

Use any of these entrypoints:

```bash
./desktop-shell/tauri-skeleton/build.sh
./desktop-shell/tauri-skeleton/build.ps1
npm --prefix desktop-shell run build:desktop
```

Use `--clean` to remove the previous export, generated icons, and old installer
artifacts before rebuilding.

The release flow now:

1. generates branded desktop icons
2. stages a desktop-only frontend export tree without Next server-only
   route handlers / middleware
3. stages a managed backend runtime bundle from `backend/`
4. builds the frontend export for Tauri packaging
5. copies the export to `companion-www`
6. runs `cargo tauri build`
7. writes `SHA256SUMS.txt` and `release-manifest.json` next to the bundle output

If the Tauri CLI is missing, the build scripts now fail immediately with the
correct `cargo install tauri-cli@^2` instruction.

The repo also now has a no-secrets desktop matrix workflow at
[`../.github/workflows/desktop-release.yml`](../.github/workflows/desktop-release.yml)
that builds unsigned desktop artifacts on Windows, macOS, and Linux and turns
`v*.*.*` tags into downloadable GitHub release assets.

See [`tauri-skeleton/RELEASE.md`](./tauri-skeleton/RELEASE.md) for release-path
details and [`tauri-skeleton/RELEASE_INPUTS.md`](./tauri-skeleton/RELEASE_INPUTS.md)
for the future inputs that only matter once public distribution trust becomes a
goal.

## Current status

This is a **runnable desktop foundation with a repeatable packaging path**.

What works:

- native desktop window with full app UI
- packaged desktop ownership of a bundled local backend runtime
- packaged desktop auto-generates and persists its local backend admin/private-plane secrets on first run
- packaged desktop-managed backend blocks legacy `16`-hex node-ID compat and direct `legacy_agent_id` lookup by default
- packaged same-origin `/api/*` path for non-privileged data
- Rust-side policy enforcement and audit
- tray/menu-bar background lifecycle
- macOS dock reopen
- optional reduced-trust browser companion opener
- branded Tauri/Windows/macOS bundle icons
- release manifest + checksum generation

What is still not done:

- code signing / notarization
- auto-update mechanism
- final installer copy / splash polish
- DM/data-plane native migration
- standalone-browser-equivalent companion parity

## Managed backend defaults

The packaged desktop-managed backend now defaults to the hardened posture for
compatibility sunset work:

- `MESH_BLOCK_LEGACY_NODE_ID_COMPAT=true`
- `MESH_ALLOW_LEGACY_NODE_ID_COMPAT_UNTIL=` unless an operator sets a dated temporary migration override
- `MESH_BLOCK_LEGACY_AGENT_ID_LOOKUP=true`

That default applies to the app-owned managed backend created under
`%LOCALAPPDATA%`. Source/server deployments remain operator-controlled and can
set those flags independently.

If a managed desktop operator leaves `MESH_BLOCK_LEGACY_NODE_ID_COMPAT=false`
in the managed backend `.env`, bootstrap now normalizes it back to `true`.
The only supported escape hatch for legacy 16-hex node IDs is a dated
`MESH_ALLOW_LEGACY_NODE_ID_COMPAT_UNTIL=YYYY-MM-DD` override.
`MESH_BLOCK_LEGACY_AGENT_ID_LOOKUP=false` is still preserved if an operator
intentionally needs that separate migration path.
