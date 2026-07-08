# Source Playbook

This playbook describes the local data sources Shadowbroker should ingest for lead generation, marketplace intelligence, and operations. Each source must be registered before automation is enabled.

## Source Intake Record

Create one record per source:

| Field | Required Detail |
|---|---|
| Source name | Agency, provider, portal, or first-party system |
| Jurisdiction | City, county, state, utility district, HOA, or platform |
| Access method | API, ArcGIS REST, Socrata, CKAN, CSV export, email alert, manual upload, or licensed vendor feed |
| Terms | Link or local copy of terms/license |
| Authentication | None, API key, account export, OAuth, or vendor credentials |
| Cadence | Realtime, hourly, daily, weekly, monthly, manual |
| Retention | Raw retention, normalized retention, evidence retention |
| Attribution | UI attribution, report attribution, internal-only note |
| Restrictions | No resale, no redistribution, rate limit, personal data handling, commercial use limits |
| Owner | Who is responsible for keeping it compliant |

## Local Government And GIS Sources

### Permits

Useful permit categories:

- Swimming pools, pool barriers, pool electrical, and pool plumbing.
- Fence, gate, retaining wall, deck, patio, pergola, and accessory structure permits.
- Roofing, siding, windows, solar, generator, HVAC, and electrical upgrades.
- New residential construction, additions, remodels, demolition, and certificate-of-occupancy events.
- Septic, well, drainage, grading, driveway, and right-of-way permits.

What to extract:

- Permit number, type, status, dates, address, parcel id, valuation, contractor, owner when legally usable, description, inspection status, and coordinates.
- Lead category, likely trade need, lead urgency, confidence, and follow-up action.
- Permit chains: pool permit plus fence permit, new-build permit plus closing, storm event plus roof permits.

Preferred access:

- Open-data API or CSV export.
- ArcGIS FeatureServer or MapServer layer.
- Official weekly report PDF only when structured data is unavailable.
- Manual upload as a fallback.

Avoid:

- Credentialed scraping that violates portal terms.
- Circumventing CAPTCHAs or access controls.
- Storing raw personal data when a parcel-level or address-level business signal is sufficient.

### Property And Parcels

Useful layers:

- Parcel polygons, address points, land use, zoning, school district, flood zone, building footprints, impervious surface, subdivision plats, easements, and right-of-way.
- Assessor values, sale date, sale price, owner mailing geography, year built, improvement value, lot size, square footage, and property class.
- Deed transfers, mortgage releases, foreclosure notices, tax delinquency lists, and new subdivision lot releases where public.

Lead signals:

- Recent closing plus high-value exterior project opportunity.
- New owner plus aged fence/roof/pool equipment.
- Large lot plus pool, fence, landscaping, or accessory structure fit.
- High-value remodel area plus contractor-intent permits nearby.

### Planning And Development

Useful sources:

- Planning commission agendas, zoning board cases, subdivision reviews, annexation notices, rezoning applications, variance requests, and road-project plans.
- Building department inspection calendars and public contractor lists where allowed.

Lead signals:

- Neighborhoods entering growth phase.
- Builders and contractors with repeated activity.
- Streets with upcoming disruption or utility upgrades.
- Commercial parcels likely to change tenant or ownership.

## Consumer And Market Behavior Sources

In-scope methods:

- First-party CRM, call logs, estimates, invoices, web analytics, ad campaign reports, quote outcomes, and service-area history.
- Public trend data, official reports, paid/licensed market datasets, weather/event overlays, and manually contributed community notes.
- Exports from accounts you control when the platform terms allow export and business analysis.
- Aggregated, non-sensitive observations from public community posts without attempting to identify or profile private individuals beyond a legitimate business context.

Out-of-scope methods:

- Using personal logins to scrape Nextdoor, Facebook groups, or private forums in ways the platform forbids.
- Joining groups under false pretenses.
- Circumventing rate limits, CAPTCHAs, privacy settings, or anti-automation controls.
- Building dossiers on private people unrelated to a legitimate business transaction.
- Recording private meetings without required consent.

Practical compliant alternatives:

- Manual clipping workflow with source URL, author visibility, date, topic, and a short operator note.
- Group-admin-approved community trend exports.
- Official ad-library, marketplace, or business-page APIs when available.
- Local survey forms, QR-code landing pages, referral forms, and opt-in neighborhood alerts.
- Aggregated topic counters instead of raw post storage.

## Normalized Objects

Shadowbroker should normalize source data into these objects:

| Object | Purpose |
|---|---|
| `jurisdiction` | County, city, district, HOA, or market area |
| `parcel` | Stable property geography and assessor facts |
| `address` | Geocoded service location |
| `permit` | Work-intent event from government records |
| `sale` | Closing, transfer, or ownership-change event |
| `project_signal` | Derived opportunity such as pool lead, fence lead, or roof lead |
| `entity` | Contractor, builder, agency, business, or known source |
| `field_observation` | Operator-captured note, media, GPS, or sensor event |
| `source_evidence` | Link, file hash, timestamp, and attribution |

## Scoring Factors

Initial score:

- Recency: newer permits, closings, or events rank higher.
- Intent strength: issued permit beats vague interest.
- Spend proxy: valuation, property value, square footage, and lot size.
- Fit: category alignment with target business.
- Competition: number of active contractors or public mentions.
- Route efficiency: distance from planned route or current van position.
- Confidence: official structured source beats manual rumor.
- Privacy risk: high-risk personal data lowers score unless needed and lawful.
