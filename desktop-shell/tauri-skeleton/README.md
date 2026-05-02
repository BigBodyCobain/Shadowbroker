# Tauri Skeleton

Cross-platform Tauri integration for the ShadowBroker desktop boundary.

## Scope

This skeleton covers the accepted native desktop foundation:

- Rust-authoritative local-control policy enforcement and audit
- cross-platform tray/menu-bar lifecycle
- packaged managed local backend runtime
- packaged loopback runtime for same-origin `/api/*`
- optional reduced-trust browser companion opener
- desktop packaging flow with branded bundle icons and release manifests

It does **not** move DM/data-plane operations into native code.

## Architecture

1. `main.rs` creates the main window programmatically and attaches an
   `initialization_script` so `window.__SHADOWBROKER_DESKTOP__` exists before
   page JavaScript runs
2. `bridge.rs` routes Tauri IPC through `policy.rs` before any privileged
   backend dispatch
3. `backend_runtime.rs` installs and launches the bundled backend runtime into
   app-local writable storage for packaged builds
4. `companion_server.rs` provides the packaged loopback HTTP origin used by:
   - the native main window for ordinary same-origin `/api/*`
   - the optional external browser companion opener
5. `tray.rs` owns tray/menu-bar restore/hide/quit behavior
6. `http_client.rs` forwards privileged native requests with the native-owned
   admin key

## Environment variables

- `SHADOWBROKER_BACKEND_URL` - Optional backend override. In packaged mode, if unset, the app launches its bundled local backend automatically.
- `SHADOWBROKER_ADMIN_KEY` - Optional admin key for privileged backend access
- `SHADOWBROKER_FRONTEND_URL` - Explicit frontend origin override for dev/custom setups

## Development

```bash
# Install Tauri CLI
cargo install tauri-cli@^2

# Start the dev shell (frontend dev server must already be running on :3000)
./dev.sh
```

Platform dependencies:

- Linux: `libwebkit2gtk-4.1-dev`, `libjavascriptcoregtk-4.1-dev`, `libayatana-appindicator3-dev`, `libxdo-dev`
- macOS: Xcode command-line tools
- Windows: Visual Studio C++ build tools

## Production build

Use whichever entrypoint matches your environment:

```bash
# POSIX shell
./build.sh

# Windows PowerShell
./build.ps1

# Cross-platform npm wrapper from repo root
npm --prefix desktop-shell run build:desktop
```

Add `--clean` when you want a fresh export/icon rebuild and old bundle
artifacts removed before packaging.

The release build now does the full packaging pipeline:

1. Generates branded icons in `src-tauri/icons/`
2. Stages a desktop-only frontend export tree that omits Next server-only
   routes/middleware (`src/app/api`, `src/middleware.ts`)
3. Stages a managed backend runtime bundle from `backend/` into
   `src-tauri/backend-runtime/`
4. Builds the frontend export with `NEXT_OUTPUT=export`
5. Copies `frontend/out` to `src-tauri/companion-www/`
6. Runs `cargo tauri build`
7. Writes `SHA256SUMS.txt` and `release-manifest.json` to
   `src-tauri/target/release/bundle/`

If `cargo tauri` is not installed, the build now fails immediately with the
required install command instead of failing after the frontend export.

See [RELEASE.md](./RELEASE.md) for the release-oriented checklist.
See [RELEASE_INPUTS.md](./RELEASE_INPUTS.md) for the future credentials/secrets
that only matter once you want signed/notarized public distribution.

## Runtime model

### Native privileged path

The 27 privileged local-control commands still go through the Rust IPC bridge.
The packaged loopback server does **not** replace that boundary.

### Packaged loopback app server

In packaged builds, `main.rs` now launches a bundled local backend by default,
then starts a loopback HTTP server and points the native window at it. That
gives the packaged desktop app ownership of both the app shell and the local
backend runtime, while keeping a real same-origin `/api/*` path for ordinary
non-privileged fetches.

The managed backend runtime also seeds and persists its own local secrets on
first launch:

- `ADMIN_KEY`
- `MESH_PEER_PUSH_SECRET`
- `MESH_DM_TOKEN_PEPPER`
- `MESH_SECURE_STORAGE_SECRET` on non-Windows

It also defaults the managed compatibility-cutoff flags to the hardened desktop
posture:

- `MESH_BLOCK_LEGACY_NODE_ID_COMPAT=true`
- `MESH_ALLOW_LEGACY_NODE_ID_COMPAT_UNTIL=` unless an operator sets a dated temporary migration override
- `MESH_BLOCK_LEGACY_AGENT_ID_LOOKUP=true`

That keeps the packaged desktop path out of the "edit `.env` by hand before it
is safe" trap for normal local users.

If a managed desktop operator leaves `MESH_BLOCK_LEGACY_NODE_ID_COMPAT=false`
in the managed backend `.env`, bootstrap now normalizes it back to `true`.
The only supported escape hatch for legacy 16-hex node IDs is a dated
`MESH_ALLOW_LEGACY_NODE_ID_COMPAT_UNTIL=YYYY-MM-DD` override. Source/server
deployments remain operator-controlled through their own env files and do not
inherit this desktop-specific default.

### Browser companion

Browser companion is:

- optional
- disabled by default
- loopback-only
- reduced-trust

It does **not** receive the native bridge injection and is **not** equivalent
to standalone browser mode. The built-in loopback server is a thin static
`/api/*` proxy and does not reproduce Next middleware, admin-session cookie
logic, or wormhole routing.

## Current status

This is now a **runnable desktop build path** with branded assets and repeatable
bundle outputs.

What works:

- Native desktop window (dev + packaged)
- Packaged bundled local backend launch + ownership
- Managed packaged backend auto-seeding of local admin/private-plane secrets
- Packaged same-origin `/api/*` path for non-privileged data
- Rust-authoritative policy enforcement and audit
- Tray/menu-bar background lifecycle
- macOS dock reopen restores the main window
- Browser companion opener with honest reduced-trust scoping
- Branded bundle icon set (`.png`, `.ico`, `.icns`, Windows tile assets)
- Release checksums + artifact manifest alongside bundle output
- GitHub Actions desktop build matrix for Windows/macOS/Linux
- Tag-driven GitHub release asset upload without required secrets

What is still not done:

- Windows code signing
- macOS notarization credentials
- Auto-update publishing
- Final installer copy / splash polish
- Standalone-browser-equivalent companion parity
