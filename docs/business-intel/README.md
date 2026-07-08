# Business Intel Program

This folder defines the private local-intelligence program we are building on top of Shadowbroker. The goal is to turn lawful public records, local GIS data, first-party field observations, and consented device telemetry into useful business and operational intelligence.

## Operating Model

Shadowbroker should stay private by default:

- Homeoffice computer runs the stack.
- TV uses the local dashboard or the `/tv` view.
- Family and internal users access through the tailnet.
- Nothing is port-forwarded or published through Funnel unless that is an explicit future decision.
- Sensitive raw inputs stay local unless a source-specific export is intentionally configured.

## First Workstreams

1. Local opportunity radar
   - Permits, inspections, parcel transfers, property sales, closings, subdivision activity, code-enforcement signals, zoning applications, and GIS layers.
   - Primary lead examples: pool permits, fence permits, additions, remodels, new-build closings, storm-damage clusters, large-lot ownership changes, and neighborhood-level demand spikes.

2. Source registry and compliance
   - Every feed gets source terms, access method, cadence, retention, and attribution.
   - Raw personally sensitive data should be minimized, redacted, or retained only when it has a clear business purpose.

3. Pixel field node
   - USB-connected Pixel phone used as a field data collector.
   - Captures first-party observations, GPS tracks, dashcam video, inertial events, network state, and operator notes where lawful.
   - Supports opt-in meeting notes/transcripts only with consent and clear labeling.

4. Van and Starlink integration
   - Van becomes a mobile collection and operations node.
   - Starlink provides uplink when cellular coverage is poor.
   - Tailnet keeps command/control private.

5. Dashboards and visualization
   - Map heat layers, lead timelines, parcel/property dossiers, source health, field tracks, van route replay, and graph/3D opportunity models.

## Documents

- [Source Playbook](source-playbook.md): local permits, GIS, home sales, and consumer-behavior sources.
- [Mobile And Van Architecture](mobile-van-architecture.md): Pixel, dashcam, sensors, Starlink, and tailnet design.
- [Use Cases](use-cases.md): lead-generation and operational-intel workflows.
- [Governance](governance.md): privacy, consent, retention, terms, and audit rules.
- [Build Roadmap](roadmap.md): implementation phases and integration sequence.

## Active Starter Markets

- [Carolina Beach / Wrightsville Beach, NC](jurisdiction-carolina-beach-wrightsville.md)
- [New Hanover County / Wilmington, NC](jurisdiction-new-hanover-wilmington.md)
- [Brunswick County / Leland, NC](jurisdiction-brunswick-leland.md)
- [Southeast NC source registry](southeast-nc-source-registry.yaml)

## Immediate Questions

To wire specific feeds, we need:

- Business verticals to optimize first, such as pool service, fencing, real estate, roofing, landscaping, cleaning, security, or home services.
- Whether the Pixel field node is a spare phone or the primary phone.
- Whether the van has OBD-II access, aux power, and a permanent Starlink mount.
