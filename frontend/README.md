# ShadowBroker Frontend

Next.js 16 dashboard with MapLibre GL and Framer Motion.

## Development

```bash
npm install
npm run dev        # http://localhost:3000
```

## API URL Configuration

The browser calls relative `/api/*` paths. The catch-all route handler at
`src/app/api/[...path]/route.ts` proxies those requests to the backend using
the server-side `BACKEND_URL` environment variable at request time.

This keeps the backend URL out of the client bundle and lets Docker or other
deployments change the backend target without rebuilding the frontend.

### Common Scenarios

| Scenario | Action needed |
| --- | --- |
| Local dev (`localhost:3000` + backend on `127.0.0.1:8000`) | None. The proxy defaults to `http://127.0.0.1:8000`. |
| Docker Compose | None. `docker-compose.yml` sets `BACKEND_URL=http://backend:8000`. |
| Backend on a different host or port | Set `BACKEND_URL` before starting the Next.js server/container. |
| Reverse proxy in front of the frontend | Point external clients at the frontend; keep `BACKEND_URL` set to the backend address reachable from the Next.js server. |

### Setting `BACKEND_URL`

```bash
# Shell (Linux/macOS)
BACKEND_URL=http://myserver:8000 npm run dev

# PowerShell (Windows)
$env:BACKEND_URL="http://myserver:8000"; npm run dev

# Docker Compose
# Edit the frontend service environment or add a compose override:
# BACKEND_URL=http://myserver:8000
```

## Theming

Dark mode is the default. A light/dark toggle is available in the left panel
toolbar. Theme preference is persisted in `localStorage` as `sb-theme` and
applied via the `data-theme` attribute on `<html>`. CSS variables in
`globals.css` define all structural colors for both themes.
