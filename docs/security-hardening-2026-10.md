# Operator HTTP security hardening

Operator endpoints now require credentials on every connection, including localhost
and the Docker bridge. Public data stays available without an operator session.

## Browser and Docker

Set the same random `ADMIN_KEY` (at least 32 characters) on the frontend and
backend. In Docker, set it in the repository's `.env` before starting Compose.
Use Settings → Admin Session to sign in. Cookies are HttpOnly and SameSite=Strict.
Origin headers, forwarded headers and source addresses never authenticate a caller.
Use HTTPS for remote browser deployments.

Behind a reverse proxy, set `SHADOWBROKER_ALLOWED_ORIGINS` on both services to the
exact public origin, for example `https://shadowbroker.example`. Separate multiple
origins with commas. Do not include paths or wildcards. Forwarded host headers do
not add trusted origins. Backend `CORS_ORIGINS` remains available for direct
browser clients.

`npm run dev` creates matching keys in `backend/.env` and `frontend/.env.local`
when missing. It preserves existing keys and refuses mismatched files. The key is
not printed. Standalone frontend/backend launches need matching configuration.
CLI clients may send `X-Admin-Key`; scoped tokens remain subject to backend scopes.
To proxy scoped tokens through Next.js, configure `MESH_SCOPED_TOKENS` on the
frontend as well as the backend.

## Native desktop and browser companion

The managed desktop backend already generates its operator key. A Rust IPC
bootstrap installs an HttpOnly session only in the native main webview; the
credential never passes through JavaScript. The packaged proxy recognizes that
session, validates the exact origin and checks the native capability policy.
Native custody and control operations continue through their existing IPC
commands. Browser companion sessions receive no privileged cookie or injected key.

An externally managed desktop backend needs `SHADOWBROKER_ADMIN_KEY`. For native
development with an external Next.js server, configure that same key on the
frontend; Rust establishes the browser session against the configured origin.

## Gateway credentials and request limits

Save the compatible provider before fetching its models. Model discovery accepts
only the saved destination; an unsaved URL cannot receive stored credentials.
Credentials in model-discovery query strings are rejected.

The backend bounds actual received bytes before parsing or authenticating bodies:
512 KiB for peer pushes, 64 KiB for peer announcements/DM replication, and 8 MiB
for other API requests. The frontend enforces matching limits on proxied bodies
and 64 KiB on session creation. Oversized bodies return HTTP 413, including
chunked requests and requests with false Content-Length headers.

## Dependencies and verification

Next.js and MapLibre were upgraded to patched releases, with patched Sharp and
PostCSS versions and a refreshed Python workspace lock. AnyIO, cryptography,
SoupSieve and urllib3 also have patched minimum versions. MapLibre 6 uses an
explicit bundled module worker and explicit GeoJSON imports. Webpack is used for
development and production because the current MapLibre bundle fails Turbopack's
dynamic-URL analysis. The desktop exporter uses the same build command.

Production application TypeScript is checked through `tsconfig.build.json`;
the full test suite is executed separately with Vitest. Historical test-fixture
TypeScript errors are excluded from the application build.

CI runs production npm auditing and Python dependency auditing, the development credential-bootstrap test and
the new operator/body-limit regression tests. The development dependency audit
still reports an unpatched `braces`/`fast-glob` chain under ESLint's Next.js
configuration; production dependency auditing excludes that build-only chain.
