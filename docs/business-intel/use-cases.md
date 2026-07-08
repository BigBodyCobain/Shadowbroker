# Business Intel Use Cases

These workflows are the first high-value ways to use the local intel system.

## Pool Permit Lead Radar

Inputs:

- Pool permits, pool electrical/plumbing permits, parcel data, recent sales, satellite/map context, neighborhood income proxy, and contractor history.

Output:

- Hot lead list by address or parcel.
- Related opportunities: fence, gate, landscaping, lighting, drainage, maintenance, pressure washing, insurance, and safety compliance.
- Map heat layer of active pool construction pockets.

Why it matters:

- Pool activity is high-intent and often triggers adjacent exterior spending.

## New Home Closing Trigger

Inputs:

- Deed transfers, MLS or licensed closing feeds, assessor updates, certificate-of-occupancy records, utility connects, and subdivision lot releases.

Output:

- New-owner action queue with recommended offer, route fit, and neighborhood context.
- Builder and subdivision trend dashboard.

Why it matters:

- New owners buy services quickly, and the first vendor relationship often sticks.

## Permit Chain Detection

Inputs:

- Permits across categories, inspection status, contractor names, parcel data, and time.

Output:

- Signals such as `pool issued -> fence likely`, `addition issued -> landscaping likely`, `roof issued after storm -> gutter/repair cluster`, and `new build closing -> outdoor package`.

Why it matters:

- The best lead is often the next project implied by the current project.

## Neighborhood Momentum Score

Inputs:

- Permit density, sale velocity, valuation changes, code-enforcement volume, school boundaries, road projects, public complaints, and first-party quote outcomes.

Output:

- Market-area score by subdivision, grid cell, or drive-time polygon.
- TV view showing pockets heating up this week.

Why it matters:

- Sales routes and ad spend should follow momentum, not static ZIP-code assumptions.

## Field Observation To Lead

Inputs:

- Pixel photos, dashcam bookmarks, GPS tracks, spoken notes with consent, and manual tags.

Output:

- Field observation attached to a parcel or route segment.
- Follow-up task if the observation matches a target signal.

Examples:

- Visible active construction.
- New development sign.
- Storm-damage cluster.
- Competitor yard signs.
- Vacant commercial unit.
- High-end outdoor project in progress.

## Competitor And Contractor Activity

Inputs:

- Permit contractor fields, public business pages, public ads, first-party observations, review counts, trucks spotted in service area, and jobsite signs.

Output:

- Contractor graph: where each competitor works, what categories they pull, and how their activity changes over time.
- Alerts when a competitor enters a target subdivision or slows down.

Guardrail:

- Track businesses and public commercial activity. Do not create private-person dossiers unrelated to a legitimate business purpose.

## Route And Territory Optimization

Inputs:

- Lead score, route distance, van position, appointment calendar, traffic context, and time windows.

Output:

- Suggested daily route.
- Nearby lead prompts during existing trips.
- Missed-neighborhood report.

Why it matters:

- Field time is expensive. The system should convert travel into intelligence.

## Storm And Weather Response

Inputs:

- Weather alerts, hail/wind history, outage reports, social/community trend counters, roof/fence permits, and field observations.

Output:

- Storm-response heat map.
- Priority neighborhoods for legitimate inspection offers.
- Permit surge detection after the event.

Guardrail:

- Do not exploit emergencies with misleading claims. Keep outreach truthful and source-backed.

## 3D Opportunity Model

Inputs:

- Project signals, permit chains, entities, neighborhoods, field observations, and source confidence.

Output:

- 3D graph where clusters represent markets and vertical height represents opportunity score or urgency.
- Animated edges show how signals imply next-best actions.

Why it matters:

- A 3D model helps see relationships that flat tables hide: neighborhoods, source confidence, contractors, and timing.
