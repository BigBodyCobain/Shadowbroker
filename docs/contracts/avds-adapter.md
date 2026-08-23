# ShadowBroker AVDS adapter contract

- Mode: `visual uplift`; evidence layer: `local-candidate`.
- Live AVDS reference observed 2026-08-23: `4.7.0`, source SHA `79342b07b061938c14101a213d1dd0c7a412d689`.
- Product stack: Next.js static semantic adapter; it does not claim `@sgeo/ui-kit` package consumption.
- Currency: source API is unverified because the exact AVDS Git object is not available in this checkout. Recheck before a release claim.

`frontend/src/styles/avds-adapter.css` owns the semantic mapping. It maps the product's existing canvas, raised surface, border, text, spacing and radius roles to named AVDS-facing variables. Public page components use those roles for the page identity and operational-state surfaces; map data, access policy, feeds and mutations stay product-owned.

The shared geometry contract is a 16px outer compact gutter, a bounded 352px left control rail, a bounded 400px right intelligence rail, and responsive full-width status content below 768px. Any future shared shell change must regress the map, layer controls, intelligence feed, search and mesh surfaces.
