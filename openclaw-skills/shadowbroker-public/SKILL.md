---
name: shadowbroker-public
description: >
  Turn your agent into a ShadowBroker. Answer questions about live aircraft,
  ships, satellites, hazards and world news from the ShadowBroker public data
  feed: where a plane or vessel is, what is near a place, what the news says
  about a topic. Read-only. No account, API key or ShadowBroker install needed.
---

# ShadowBroker Public Skill

You have read-only access to the **ShadowBroker public feed**: the same live
map data the public ShadowBroker viewer shows. It covers aircraft (commercial,
private, military, tracked), ships, satellites, earthquakes, fires, weather
alerts, internet outages, global incidents (GDELT), news, radio and mesh node
locations, public cameras and infrastructure.

This is the public sibling of the full `shadowbroker` skill. The command names
and answer shapes are the same, so anything you know from one carries over.
The differences:

| | Public skill (this one) | Full `shadowbroker` skill |
|---|---|---|
| Needs | Nothing | Your own ShadowBroker install |
| Reads | The published feed files | Your install's live backend |
| Writes (pins, posts, messages, watches) | **Never** | Yes |
| Secrets | None | Your HMAC secret |

## Fast path (read this first)

```python
from sb_public import ShadowBrokerPublicClient
sb = ShadowBrokerPublicClient()          # reads SHADOWBROKER_PUBLIC_URL

answer = await sb.ask("where is N189AM")            # default for every question
answer = await sb.ask("ships near 36.85, -76.30")
answer = await sb.ask("news about the Red Sea")
status = await sb.channel_status()                    # is the feed live?
```

Or from a shell, one JSON answer per call:

```bash
python sb_public.py ask "where is the Ever Given"
python sb_public.py cmd find_flights '{"callsign": "RCH"}'
python sb_public.py status
```

`ask` routes a plain-language question to the right command and runs it. Its
answer is `{"ok": true, "data": {"route": {...}, "result": {"ok": true, "data": {...}}}}`.
Use the structured commands below when you already know what you want.

## Commands

All return `{"ok": true, "data": ...}` or `{"ok": false, "detail": "..."}`.

| Command | Use it for | Key arguments |
|---|---|---|
| `find_entity` | **One aircraft or ship**, exact match first | `query`, or `registration` / `callsign` / `icao24` / `mmsi` / `imo` / `name`; `owner`; `entity_type` (`aircraft` or `ship`) |
| `find_flights` | Flight search | `callsign`, `registration`, `icao24`, `owner`, `query`, `categories`, `limit` |
| `find_ships` | Ship search | `mmsi`, `imo`, `name`, `query`, `limit` |
| `entities_near` | What is within a radius | `lat`, `lng`, `radius_km`, `entity_types`, `limit` |
| `brief_area` | Area brief: nearby movers, hazards, topic news | `lat`, `lng`, `radius_km`, `query` |
| `search_news` | News and incident search | `query`, `limit`, `include_gdelt` |
| `get_summary` | Which layers exist and how many records each has | none |
| `get_layer_slice` | Raw records for named layers | `layers`, `limit_per_layer` |
| `channel_status` | Feed age and health | none |
| `run_playbook` | Pre-batched: `status_check`, `hot_snapshot`, `morning_brief`, `area_brief`, `track_snapshot` | `name`, plus the playbook's arguments |

```python
await sb.send_command("find_entity", {"registration": "N189AM"})
await sb.send_command("find_entity", {"owner": "air ambulance", "entity_type": "aircraft"})
await sb.send_command("entities_near", {"lat": 36.85, "lng": -76.3, "radius_km": 40, "entity_types": ["ships"]})
await sb.send_batch([{"cmd": "get_summary"}, {"cmd": "search_news", "args": {"query": "earthquake"}}])
```

Layer aliases work in `entity_types`, `categories` and `layers`: `military`,
`tracked`, `jets`, `ship`, `quakes`, `fires`, `cameras`, `receivers`, `uap`,
`cyber`, `malware`.

### Things to know about the answers

- **Aircraft are five layers:** `commercial_flights`, `private_flights`,
  `private_jets`, `military_flights`, `tracked_flights` (notable aircraft),
  plus `uavs`. Add their counts from `get_summary` for "how many aircraft".
  Ships are the single layer `ships`.
- **Units.** `altitude` is metres (as the app stores it); `altitude_ft` is the
  same height in feet. `speed_knots` is knots. `heading` is degrees.
  `distance_km` is kilometres. Ship `speed` is knots.
- **Defaults.** `entities_near`: `radius_km` 50, `limit` 25, and by default
  only movers (tracked, military and private-jet aircraft, ships, UAVs,
  satellites). Name other layers in `entity_types` to include them.
  `find_flights` / `find_ships` limit 25, `find_entity` 10, `search_news` 10.
- **Cut-off results.** `truncated: true` means more matched than were
  returned. `entities_near` also gives `total`, the full number in range.
- **A radius in the question is honoured.** `ask "ships within 30 km of
  36.85, -76.30"` searches 30 km. Miles and nautical miles work too.
- **News sources.** `search_news` searches curated headlines (`news`) and,
  unless `include_gdelt` is false, GDELT incident clusters. GDELT adds volume
  but is noisier: its hits are marked `"source_layer": "gdelt"` and
  `"match": "headline"` (the headline mentions the topic) or `"location"`
  (only the place does). Prefer `news` and `headline` hits when quoting.
- **Shells.** The JSON argument examples are for bash. In PowerShell wrap the
  JSON in single quotes and double the inner quotes, or use `ask` instead.

## How to answer well

1. **Check freshness when it matters.** `channel_status` gives `age_seconds`
   and `stale`. If the feed is stale, say the position is from that time, not
   live.
2. **Exact first.** For a tail number, callsign, MMSI or exact ship name use
   `find_entity` (or just `ask`). It reads one small index file. Owner and
   free-text searches download whole layers, so use them only when needed.
3. **Places need coordinates.** This skill does not look up place names. Use
   coordinates you already know, or ask the user for them.
4. **Say what you found and where it came from.** Give the position, the
   layer it came from, and that the source is the ShadowBroker public feed.
5. **Not found means not in the feed right now.** Aircraft and ships appear
   only while they are broadcasting and covered. Say that; do not guess.
6. **One call, not a loop.** Use `send_batch` or a playbook rather than many
   single commands. Do not poll faster than the feed updates (`cadence`).

## What this skill will not do

- **No writes.** `place_pin`, `post_to_gate`, `send_dm`, `add_watch` and every
  other command that changes or sends something returns
  `"not available in the public skill"` without making any request. Those
  need the full skill and your own install.
- **No private layers.** Only what the feed publishes exists here. A layer
  the feed withholds comes back under `not_published`.
- **No people lookups.** The feed is about vehicles, places and events. Do
  not use it to locate or follow a private individual.
- **No safety-of-life use.** Positions come from public broadcasts and can be
  late, missing or wrong. Never use them for navigation or emergencies.

## Setup

Python 3.10 or newer, standard library only. Set the feed address:

```bash
export SHADOWBROKER_PUBLIC_URL=https://<the ShadowBroker public data address>
```

That is the only setting. There is no key to obtain and nothing to sign in to.
