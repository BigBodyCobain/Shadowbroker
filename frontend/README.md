# ShadowBroker Frontend

Next.js 16 dashboard with MapLibre GL, Cesium, and Framer Motion.

## Development

```bash
npm install
npm run dev        # http://localhost:3000
```

## API URL Configuration

The frontend needs to reach the backend (default port `8000`). Resolution order:

1. **`NEXT_PUBLIC_API_URL`** env var — if set, used as-is (build-time, baked by Next.js)
2. **Server-side (SSR)** — falls back to `http://localhost:8000`
3. **Client-side (browser)** — auto-detects using `window.location.hostname:8000`

### Common scenarios

| Scenario                                        | Action needed                                                   |
| ----------------------------------------------- | --------------------------------------------------------------- |
| Local dev (`localhost:3000` + `localhost:8000`) | None — auto-detected                                            |
| LAN access (`192.168.x.x:3000`)                 | None — auto-detected from browser hostname                      |
| Public deploy (same host, port 8000)            | None — auto-detected                                            |
| Backend on different port (e.g. `9096`)         | Set `NEXT_PUBLIC_API_URL=http://host:9096` before build         |
| Backend on different host                       | Set `NEXT_PUBLIC_API_URL=http://backend-host:8000` before build |
| Behind reverse proxy (e.g. `/api` path)         | Set `NEXT_PUBLIC_API_URL=https://yourdomain.com` before build   |

### Setting the variable

```bash
# Shell (Linux/macOS)
NEXT_PUBLIC_API_URL=http://myserver:8000 npm run build

# PowerShell (Windows)
$env:NEXT_PUBLIC_API_URL="http://myserver:8000"; npm run build

# Docker Compose (set in .env file next to docker-compose.yml)
NEXT_PUBLIC_API_URL=http://myserver:8000
```

> **Note:** This is a build-time variable. Changing it requires rebuilding the frontend.

## Theming

Dark mode is the default. A light/dark toggle is available in the left panel toolbar.
Theme preference is persisted in `localStorage` as `sb-theme` and applied via
`data-theme` attribute on `<html>`. CSS variables in `globals.css` define all
structural colors for both themes.
