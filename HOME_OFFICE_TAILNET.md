# Homeoffice Tailnet Dashboard

This setup runs ShadowBroker on an always-on homeoffice computer and exposes the dashboard privately over your Tailscale tailnet. The TV connected to the same computer can use the local URL directly.

## Design

- Docker runs the backend and frontend with `restart: unless-stopped`.
- Ports stay bound to `127.0.0.1` on the host.
- Tailscale Serve can publish the frontend to the tailnet over HTTPS.
- The backend is not directly exposed; the frontend proxies `/api/*` to the backend over Docker networking.
- Tailscale Funnel should stay off unless you intentionally want public internet exposure.

## First Run On The Homeoffice Computer

Prerequisites:

- Docker Desktop
- Tailscale, signed into your tailnet
- PowerShell

From the repo root:

```powershell
.\scripts\run-homeoffice-tailnet.ps1 -Serve
```

The script will:

- Create missing local `.env` values without overwriting existing ones.
- Generate local admin/storage secrets if they do not already exist.
- Build and start the local Docker stack with `docker-compose.homeoffice.yml`.
- Run `tailscale serve --bg 3000` when `-Serve` is provided.

Local TV URL:

```text
http://127.0.0.1:3000
```

Tailnet URL:

```powershell
tailscale serve status
```

If MagicDNS is enabled, the URL will look like:

```text
https://homeoffice.<tailnet-name>.ts.net
```

## Daily Operation

Start or update:

```powershell
.\scripts\run-homeoffice-tailnet.ps1 -Serve
```

Start without rebuilding images:

```powershell
.\scripts\run-homeoffice-tailnet.ps1 -Serve -SkipBuild
```

Logs:

```powershell
docker compose -f docker-compose.yml -f docker-compose.homeoffice.yml logs -f backend
```

Stop:

```powershell
docker compose -f docker-compose.yml -f docker-compose.homeoffice.yml down
```

Disable tailnet serving:

```powershell
tailscale serve reset
```

## TV Kiosk

For a TV directly connected to the homeoffice computer, open:

```text
http://127.0.0.1:3000
```

For a browser on another tailnet device, use the Tailscale Serve HTTPS URL from:

```powershell
tailscale serve status
```

## Security Notes

- Keep `BIND=127.0.0.1`.
- Do not port-forward this dashboard through your router.
- Do not use `tailscale funnel` for this unless you explicitly want public internet access.
- Use Tailscale ACLs if you want only specific users/devices to reach the dashboard.
- Keep raw marketplace/community inputs to authorized exports, licensed feeds, public data, first-party data, or notes you are allowed to process.
- Add optional API keys to `.env` only on the homeoffice machine.
