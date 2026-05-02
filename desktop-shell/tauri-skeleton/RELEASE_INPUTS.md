# Future Release Inputs

You can ignore this file until you care about public distribution. The repo can
already build unsigned desktop artifacts locally and in GitHub Actions without
any secrets.

## What works now with zero input

- Windows, macOS, and Linux desktop builds in GitHub Actions
- PR/main-branch artifact builds through `.github/workflows/desktop-release.yml`
- tag-driven GitHub release asset upload for `v*.*.*`
- unsigned installers/bundles plus `release-manifest.json`, `SHA256SUMS.txt`,
  and Tauri updater metadata when the updater private key is available locally

## What you only need later

### Windows public trust

Unsigned Windows installers still run, but SmartScreen may warn.

If you later want signed Windows `.msi` / `.exe` bundles, you will eventually
need:

- a code-signing certificate or signing service
- the provider-specific credentials/password
- a final choice of signing tool/provider

This repo does **not** auto-sign Windows bundles yet. The workflow keeps
Windows unsigned on purpose until you pick a provider.

### macOS public trust

Unsigned macOS builds are fine for internal testing, but public distribution
usually wants Apple signing/notarization.

If these GitHub Actions secrets are present, the desktop workflow forwards them
to the Tauri build:

- `APPLE_CERTIFICATE`
- `APPLE_CERTIFICATE_PASSWORD`
- `APPLE_SIGNING_IDENTITY`
- `APPLE_ID`
- `APPLE_PASSWORD`
- `APPLE_TEAM_ID`

In plain language, that means you would eventually need:

- an Apple Developer account
- a Developer ID Application certificate export
- the certificate password
- your Apple team ID
- an app-specific password for notarization

If those secrets are absent, the macOS build still runs. It just stays unsigned
and unnotarized.

### Linux publication

Linux usually does not require a comparable account just to build artifacts.

You only need extra inputs later if you want things like:

- signed apt/rpm repositories
- distro-specific repository publication
- a permanent download host for direct package links

### In-app updates

The desktop app now uses the Tauri updater when it is running as a packaged
install. That requires the updater signing key generated for this app, but it
does not require your government name.

For local builds, keep this ignored file safe:

```text
release-secrets/shadowbroker-updater.key
release-secrets/shadowbroker-updater.key.pass
```

For CI/release builds, set the same key through these environment variables or
GitHub secrets:

- `TAURI_SIGNING_PRIVATE_KEY`
- `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`

Publishing still means uploading the generated `latest.json`, installer, and
matching `.sig` files to the GitHub release.

Packaged desktop builds now bundle and own a local backend runtime by default,
so the desktop installer/update path updates the app shell and that bundled
backend together. That still does **not** replace Docker updates or external
backend overrides.

## What to do right now

If you want test builds and downloadable installers right now, you do not need
to buy anything or set any secrets:

1. open a PR or push to `main` to get CI desktop artifacts
2. push a `vX.Y.Z` tag when you want GitHub release assets
3. use the uploaded artifacts as unsigned internal/test builds
