# ShadowBroker public viewer

A look-only copy of the ShadowBroker map for a public website. Visitors can
pan, zoom, filter and switch layers. Nothing they do can send a message, post,
change a setting, start a scan or spend an API credit, and no API key is ever
in what they download.

Everything for the viewer lives in this folder. Nothing in `frontend/` or
`backend/` is edited for it, so the full app is unchanged.

## How it fits together

```
 engine (private)            bridge (private)           public
 ───────────────────         ─────────────────          ─────────────────────────
 normal backend,      ──►    copies approved     ──►    data files on a static host
 all keys, loopback          map data out               viewer site (static files)
 only, no networks           as plain files                    ▲
                                                        visitors' browsers
```

Data moves one way. The public side holds copies; it has no address for the
engine and no code that could reach one.

| Part | Folder | What it is |
| --- | --- | --- |
| Engine launcher | `engine/` | Starts the normal backend on 127.0.0.1 with the community networks off |
| Bridge | `bridge/` | Reads the engine over loopback, writes the approved data as JSON files |
| Viewer site | `web/` | Builds the static site from a copy of `frontend/` |
| Chat (optional) | `chat/` | A public chat room on a separate hosted login service. See `chat/README.md` |
| The list | `public-layers.json` | The one list of what is public. Engine, bridge and viewer all follow it |

## Run it locally

```bash
# 1. Engine. Needs a checkout with a fresh backend/data folder, and
#    `npm ci` run once in backend/ (the ship feed uses a small Node helper).
python viewer/engine/run_public_engine.py --port 8011 --keys-from /path/to/an/install/backend/.env

# 2. Bridge: writes data files every 15 s (fast) and 120 s (slow).
python viewer/bridge/bridge.py --out viewer/web/.data

# 3. Viewer: build once (needs `npm ci` in frontend/), then preview.
node viewer/web/build.mjs
node viewer/web/serve.mjs            # http://127.0.0.1:4173
```

`--keys-from` lends the engine the upstream keys it needs for aircraft, ships
and fires. It reads only the names listed under `engine_keys` in
`public-layers.json`; the admin key, mesh secrets and paid-tool keys in that
file are ignored. The keys stay in the engine's memory. Without it the engine
still runs, with far fewer aircraft and almost no ships.

For a real deployment, build with the data host's address and upload
`viewer/web/dist/`:

```bash
NEXT_PUBLIC_SB_DATA_BASE=https://data.example.org node viewer/web/build.mjs
```

## What keeps it safe

Several independent layers, so one mistake does not expose anything.

1. **No server behind the site.** The viewer is static files. The engine
   listens on loopback only and is never published.
2. **Only listed data leaves.** The bridge publishes a data key only if
   `public-layers.json` marks it public. Keys it does not know are withheld.
3. **Secret check on every file.** Before writing, the bridge compares the
   output against the engine's configured secret values and blanks any URL
   that carries a credential. A hit drops the whole cycle.
4. **Owner-only code is not in the build.** The build copies `frontend/`,
   swaps owner-only modules for inert stand-ins (`web/overlay/`), applies a
   few text cuts (`web/cuts.json`) and deletes every source file the viewer
   page does not reach.
5. **Network guard.** `web/overlay/src/viewer/netGuard.ts` checks every
   request from page code. Only read requests for the site's own files, the
   data files and a short list of map hosts go out. App routes (`/api/...`)
   are refused inside the browser; sockets are disabled.
   If the optional chat is configured, signing in and posting go to that
   one separate service and nowhere else.
6. **Browser policy.** The page's Content-Security-Policy lists the same
   hosts, so the browser enforces the rule even for code the guard never sees.
7. **Build-time inspection.** `web/check-dist.mjs` fails the build if a
   secret name, a key-shaped string or an unlisted app route is in the output.

## Things visitors open themselves

Some layers show a location and hand the visitor to the source's own site:

- **Cameras** load in the visitor's browser straight from the camera's public
  https address. The bridge drops any camera that would need a relay.
- **Radio receivers (KiwiSDR)** and **scanners (OpenMHZ)** are map markers
  with a button that opens the provider's site in a new tab. Listening, and
  any sign-in the provider asks for, happens there.

In every case the viewer supplies an address and nothing else.

## Changing what is public

Edit `public-layers.json`, then restart the engine and bridge.

- `engine_layers`: which fetchers the engine runs. Anything not listed is off.
- `keys`: which data keys the bridge may publish, with `"public": true|false`
  and a reason when withheld.

To hide a layer switch in the viewer, add it to `VIEWER_HIDDEN_LAYERS` in
`web/overlay/src/viewer/config.ts`.

## When the app changes

The viewer follows `frontend/` automatically, with three tripwires that stop
the build instead of shipping something unreviewed:

- a cut in `cuts.json` no longer matches the app's code;
- an overlay stand-in no longer has a file to replace;
- a new app route or secret name shows up in the built files.

Each failure names the file. Fix the cut, stand-in or allowlist, and rebuild.

## Tests

```bash
python -m pytest viewer/bridge -q
python -m pytest viewer/engine -q
node --test viewer/web/tests/guardRules.test.ts viewer/web/tests/layerPrefs.test.ts
node viewer/web/build.mjs        # ends with the built-site inspection
```

## Not included yet

- Uploading to a data host. The bridge writes to a folder; serve that folder
  (nginx) or sync it to object storage.
- Layers withheld in `public-layers.json`: Telegram, markets, LiveUAMap.
- Stream-playlist (HLS) cameras and cameras that need server-side decoding.
- Flight and ship trails, flight routes, place-name search, Time Machine.
