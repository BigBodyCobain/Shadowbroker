# ShadowBroker AVDS visual uplift — local candidate

Date: 2026-08-23. Mode: visual uplift. The live AVDS reference reported version
`4.7.0` and source SHA `79342b07b061938c14101a213d1dd0c7a412d689`; its exact
source object was unavailable in this checkout, so this is a static semantic
adapter and not a package-consumption or source-current claim.

## Implemented mapping

- `frontend/src/styles/avds-adapter.css` maps the existing canvas, raised
  surface, borders, text roles, spacing and radii to named semantic adapter
  roles.
- The public map shell has a clear identity surface and a truthful health
  surface with loading, available, degraded and unavailable states.
- Decorative sci-fi chrome and fabricated status metrics were removed.
- At widths up to 767px, the two side rails use single-rail behaviour: opening
  one closes the other, avoiding a controls/feed overlap while retaining both
  rail toggles.
- The page now has one document-level H1; the map-layer title is an H2. The
  dismiss actions for first-time setup, startup cache and release notes use
  explicit accessible labels.

## Evidence boundary

The candidate is local-only. A `390x844` browser pass confirms the heading
hierarchy, labelled modal exits and the compact map shell. It deliberately
shows the unavailable-service state because the local frontend was started
without a backend; that is not runtime or public acceptance. The
machine-readable anti-generative/visual-craft ledgers pass their supplied AVDS
validators without unresolved findings. Any public AVDS status must be
reconciled with the actual deployed release identity; the existing public 0/4
adoption file is not treated as evidence for this working tree.
