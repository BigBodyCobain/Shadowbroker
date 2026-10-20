# APRS-IS receive configuration

Shadowbroker treats public APRS-IS as community infrastructure. Receive access is therefore **off by default** and public-server subscriptions must be geographically bounded.

## Public APRS-IS (recommended client mode)

Set a geographic center and a reasonable radius in `.env`:

```env
APRS_IS_ENABLED=true
APRS_IS_LAT=40.7128
APRS_IS_LON=-74.0060
APRS_IS_RADIUS_KM=100
```

Docker Compose passes these values to the backend automatically. The default host is `rotate.aprs2.net:14580`, the APRS-IS user-defined filtered client port.

Shadowbroker constructs a server-side range filter of the form:

```text
r/<latitude>/<longitude>/<radius-km>
```

For public APRS-IS hosts, `APRS_IS_RADIUS_KM` must be between **1 and 500 km**. Missing coordinates, invalid coordinates, or a larger radius fail closed: the APRS receive bridge does not connect.

Optional public-client settings:

```env
APRS_IS_HOST=rotate.aprs2.net
APRS_IS_PORT=14580
APRS_IS_CALLSIGN=N0CALL
APRS_IS_MAX_SIGNALS=5000
```

`APRS_IS_MAX_SIGNALS` is hard-capped at 20,000 and only recent observations are published.

## Dedicated/private APRS-IS server

Operators who run or control their own APRS-IS aggregation server can opt into private-server mode:

```env
APRS_IS_ENABLED=true
APRS_IS_PRIVATE_SERVER=true
APRS_IS_HOST=aprs.internal.example
APRS_IS_PORT=14580
APRS_IS_FILTER=t/p
```

In private-server mode, `APRS_IS_FILTER` may be any filter accepted by that server, or blank to use the server's default. Shadowbroker refuses to enable private/full-feed mode when the configured host is a known public APRS-IS domain such as `*.aprs2.net`, `*.aprs-is.net`, or `*.aprs.net`.

Use dedicated infrastructure for genuinely global/full-feed APRS collection. Do not point an unbounded client at public Tier-2 filtered servers.

## Runtime behavior

- APRS and Meshtastic now have independent connection lifecycles.
- Turning the APRS layer off stops the APRS receive bridge; leaving Meshtastic on does not restart it.
- Failed APRS connections use exponential reconnect backoff with jitter (30 seconds up to 15 minutes) instead of reconnecting every 15 seconds forever.
- APRS receive memory is bounded, and only observations from the recent retention window are published.
- APRS transmit remains a separate operator-initiated path and is not enabled by `APRS_IS_ENABLED`.
