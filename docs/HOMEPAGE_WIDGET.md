# Home dashboard widgets (Homepage and friends)

Shadowbroker exposes a small, flat JSON summary at **`/api/summary`** so you can
show the global threat level and a few headline counts on a self-hosted start
page such as [Homepage](https://gethomepage.dev). It's a few hundred bytes, so
it's fine to poll every few seconds (rate limit: 60 requests/minute per client).

It works on both ports:

- `http://localhost:3000/api/summary`: through the dashboard, which forwards
  `/api/*` to the backend. Use this one; it's the port you already open.
- `http://localhost:8000/api/summary`: straight from the backend.

No login is needed. The summary only contains numbers the dashboard already
shows, the same as `/api/health`.

## Example response

```json
{
  "threat_level": "GUARDED",
  "threat_score": 28,
  "threat_color": "#3b82f6",
  "threat_driver": "1 CRITICAL-tier news item",
  "flights": 6811,
  "military_flights": 130,
  "private_flights": 3164,
  "tracked_flights": 309,
  "ships": 11,
  "satellites": 384,
  "uavs": 0,
  "earthquakes": 0,
  "incidents": 1426,
  "gps_jamming_zones": 1,
  "news": 50,
  "fires": 0,
  "cctv": 0,
  "last_updated": "2026-11-04T22:24:00.853760",
  "version": "0.9.84"
}
```

| Field | Meaning |
|---|---|
| `threat_level` | `GREEN`, `GUARDED`, `ELEVATED`, `HIGH` or `SEVERE`; `UNKNOWN` until the first news cycle finishes after startup |
| `threat_score` | 0–100 score behind the level (`null` while `UNKNOWN`) |
| `threat_color` | Hex color the dashboard uses for the level |
| `threat_driver` | The top reason for the current level |
| `flights` | Commercial flights |
| `military_flights`, `private_flights`, `tracked_flights` | Other aircraft groups (`private_flights` includes private jets) |
| `ships`, `satellites`, `uavs`, `earthquakes`, `news`, `fires`, `cctv` | Item counts for those layers |
| `incidents` | Global incidents (LiveUAMap + GDELT) |
| `gps_jamming_zones` | Active GPS jamming zones |
| `last_updated` | When the data was last refreshed |
| `version` | Shadowbroker version |

Counts for layers you've switched off read `0`.

## Homepage setup

Add a service to Homepage's `services.yaml` using the built-in
[Custom API widget](https://gethomepage.dev/widgets/services/customapi/). Pick
any four fields (the default block view shows four):

```yaml
- Intel:
    - Shadowbroker:
        href: http://shadowbroker.lan:3000
        description: Global threat level
        widget:
          type: customapi
          url: http://shadowbroker.lan:3000/api/summary
          refreshInterval: 30000
          mappings:
            - field: threat_level
              label: Threat
            - field: flights
              label: Flights
              format: number
            - field: military_flights
              label: Military
              format: number
            - field: incidents
              label: Incidents
              format: number
```

For a longer list instead of four blocks, add `display: list` under `widget:`
and map as many fields as you like.

## Pointing Homepage at Shadowbroker

Homepage fetches widget data from its own server, not your browser, so the URL
has to be reachable from wherever Homepage runs:

- **Homepage installed directly on the same machine:** `http://localhost:3000/api/summary`.
- **Homepage in Docker on the same machine:** `localhost` there means the
  Homepage container itself. Use `http://host.docker.internal:3000/api/summary`
  (Docker Desktop; on Linux add `extra_hosts: ["host.docker.internal:host-gateway"]`
  to Homepage's compose service), or put both on one Docker network and use
  `http://shadowbroker-frontend:3000/api/summary`.
- **Homepage on another machine:** Shadowbroker binds to `127.0.0.1` by default,
  so other machines can't reach it. Share it on your network first (see
  "Sharing the dashboard on your network" in the README; set a strong
  `ADMIN_KEY` and LAN mode), then use `http://<shadowbroker-ip>:3000/api/summary`.
  `/api/summary` stays readable in LAN mode without signing in.

## Other tools

Anything that can poll JSON works the same way: Homarr's custom API widget,
Uptime Kuma's "HTTP(s) - Json Query" monitor (e.g. alert when
`threat_level` is `HIGH` or `SEVERE`), Home Assistant's REST sensor, and so on.
