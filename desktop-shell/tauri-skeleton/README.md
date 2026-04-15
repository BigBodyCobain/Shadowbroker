# Tauri Skeleton

This folder is the first concrete Tauri-side integration skeleton for the desktop boundary.

## Scope

It is intentionally limited to the first trusted local control-plane command set:

- Wormhole lifecycle
- protected settings reads/writes
- update trigger

It does **not** attempt to move DM/data-plane operations yet.

## What this scaffold demonstrates

1. a native `invoke_local_control` command entrypoint
2. a small Rust-side router for the first command set
3. backend HTTP delegation with native-side admin-key ownership
4. a simple webview runtime injection path for:
   - `window.__SHADOWBROKER_DESKTOP__.invokeLocalControl(...)`

## Important note

This is a scaffold, not a fully integrated desktop app yet. It exists so the next Tauri pass has a
clear structure instead of starting from scratch.

## Shared contract

The command names this scaffold must track are defined in:

- `F:\Codebase\Oracle\live-risk-dashboard\frontend\src\lib\desktopControlContract.ts`
- `F:\Codebase\Oracle\live-risk-dashboard\frontend\src\lib\desktopControlRouting.ts`
