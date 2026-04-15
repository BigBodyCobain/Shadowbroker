# Desktop Shell Scaffold

This folder is the first native-side scaffold for the staged desktop boundary.

## Purpose

It gives the future Tauri/native shell a concrete shape for:

- command routing
- handler grouping
- runtime bridge installation

without forcing a packaging migration yet.

## Source of truth

The shared desktop control contract still lives in:

- `F:\Codebase\Oracle\live-risk-dashboard\frontend\src\lib\desktopControlContract.ts`

The native-side scaffold imports that contract rather than redefining it.

## First command scope

The initial native command set covers only:

- Wormhole lifecycle
- protected settings get/set
- update trigger

That is deliberate. The goal is to move the local privileged control plane first, not the entire
mesh data plane.

## Scaffold layout

- `F:\Codebase\Oracle\live-risk-dashboard\desktop-shell\src\types.ts`
- `F:\Codebase\Oracle\live-risk-dashboard\desktop-shell\src\handlers\wormholeHandlers.ts`
- `F:\Codebase\Oracle\live-risk-dashboard\desktop-shell\src\handlers\settingsHandlers.ts`
- `F:\Codebase\Oracle\live-risk-dashboard\desktop-shell\src\handlers\updateHandlers.ts`
- `F:\Codebase\Oracle\live-risk-dashboard\desktop-shell\src\nativeControlRouter.ts`
- `F:\Codebase\Oracle\live-risk-dashboard\desktop-shell\src\runtimeBridge.ts`

## How to use later

When the Tauri shell is introduced, its command layer should:

1. receive `invokeLocalControl(command, payload)`
2. dispatch through `createNativeControlRouter(...)`
3. return the handler result back to the frontend bridge

This keeps the frontend contract stable while shifting privileged ownership into the native shell.
