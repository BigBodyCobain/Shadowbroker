# Jurisdiction Profile: Carolina Beach / Wrightsville Beach, NC

## Identity

- Name: Carolina Beach / Wrightsville Beach
- State: North Carolina
- County: New Hanover
- Primary focus: beach-town permit activity near the homeoffice base
- Registry id: `nc-carolina-beach-wrightsville-beach`
- Initial business categories: pools, fences, hardscape, fill/grade/clear, additions, renovations, new construction, docks, bulkheads, CAMA/coastal work, storm/flood response

## Homeoffice Handling

The homeoffice computer and TV dashboard are in Carolina Beach. The exact street address is intentionally not stored in tracked repo docs. Use the ignored local note at `.local-docs/business-intel/private-homeoffice.md` for exact geofence, route origin, and device placement details.

## Verified Official Sources

| Source | URL | Type | Access | Initial Use |
|---|---|---|---|---|
| Carolina Beach Building & Zoning Permits | https://www.carolinabeach.gov/256/Building-Zoning-Permits | Official permit page | Public | Town/county permit routing and active development map |
| Carolina Beach Apply for a Permit | https://www.carolinabeach.gov/257/Apply-for-a-Permit | Official permit page | Public | COAST vs town portal routing |
| Carolina Beach Online Permitting Portal | https://www.carolinabeach.gov/174/Online-Permitting-Portal | Official portal instructions | Public reference, account portal | Manual verification |
| Carolina Beach Development Permits Map | https://arcg.is/1O4SPm2 | ArcGIS web app / Cityworks layers | Public map | Active/under-construction town permit feed |
| Wrightsville Beach Planning & Inspections | https://www.townofwrightsvillebeach.com/189/Planning-Inspections | Official department page | Public | Permit categories and contacts |
| Wrightsville Beach Permit Map | https://www.google.com/maps/d/viewer?mid=11_OxrBl-obbqGnHsWvSbVyoLBC8 | Google My Maps / KML | Public map | Active permit feed and history |
| Wrightsville Beach Building Permit Form | https://www.townofwrightsvillebeach.com/FormCenter/Planning-Inspections-Department-6/Apply-for-a-Building-Permit-55 | Official form page | Public form | Permit category reference |

## Carolina Beach Notes

Carolina Beach states that New Hanover County Building Safety issues residential/commercial building permits and trade permits in town. Town permits include residential fence, driveway/hardscaping, fill/grade/clear, small accessory structures, fire permits, business registration, sidewalk cafe, vending/beach services, and temporary signs.

The town's active development map is especially useful because its webmap exposes Cityworks FeatureServer layers for:

- Residential fence permits
- Residential swimming pool permits
- Residential driveway/hardscaping permits
- Residential fill/grade/clear permits
- Residential accessory structure permits
- Residential new construction permits
- Residential addition permits
- Residential renovation/repair permits
- Commercial fence, pool, new construction, alteration/addition, renovation/repair, sign, demo, hardscaping, and fill/grade/clear permits

Common fields across tested Cityworks permit layers include:

- `CASE_NUMBER`, `CASE_TYPE`, `CASE_TYPE_DESC`, `SUB_TYPE`, `SUB_TYPE_DESC`
- `CASE_NAME`, `Location`, `CASE_STATUS`
- `BUSINESS_NAME`, `DATE_ACCEPTED`, `DATE_ENTERED`
- `PROJECT_CODE`, `PROJECT_DESC`
- `CX`, `CY`

## Wrightsville Beach Notes

Wrightsville Beach states that its Planning & Inspections Department handles municipal planning/permitting, zoning permits, CAMA minor permits, building inspections, building permits, code enforcement, and conditional use permits.

The town FAQ says Wrightsville Beach maps active permits daily by calendar year and points residents to a public Permit Map for permit-status checks. The permit map is available as Google My Maps/KML and includes permit placemarks with fields such as address, approval date, status, permit type, project description, issuer, final inspection date, and coordinates.

The building permit form page says the application covers building, demolition, plumbing, irrigation, piers/docks/bulkheads, and signs. This is a strong coastal-work signal source, but form submission and reCAPTCHA-protected workflows should not be automated.

## Lead Plays

1. Beach pool to fence chain
   - Carolina Beach has explicit residential/commercial pool and fence permit layers.
   - Pool permits should trigger fence/gate/lighting/landscaping/drainage follow-ups.

2. Fill/grade/clear and hardscape signal
   - These permits often precede exterior work, drainage issues, driveway changes, accessory structures, or storm/flood mitigation.

3. New construction and additions
   - New residential construction and addition layers should feed move-in, fence, security, landscaping, and exterior project scoring.

4. Waterfront work
   - Wrightsville Beach permits include piers, docks, bulkheads, boatlift-style descriptions, CAMA, and coastal work.
   - These are useful for marine contractors, high-value exterior services, drainage, and compliance follow-up.

5. Storm and flood response
   - Beach towns should be scored with storm, flood, roof, siding, window, elevation, piling, bulkhead, and drainage keywords.

## Implementation Order

1. Import Carolina Beach Cityworks public map layers for residential pool, fence, hardscaping, fill/grade/clear, new construction, additions, and renovations.
2. Import New Hanover County BuildingPermits and filter `CITY = CAROLINA BEACH` and `CITY = WRIGHTSVILLE BEACH`.
3. Parse Wrightsville Beach permit KML and normalize current-year/active placemarks first.
4. Add parcel joins using New Hanover parcels and Carolina Beach parcel layer where useful.
5. Add homeoffice-origin drive-time scoring from the ignored local address config.
6. Add coastal-specific scoring: CAMA, dock, bulkhead, pier, piling, flood, elevation, stormwater, and drainage.

## Restrictions And Review

- Keep the exact homeoffice address out of tracked docs and source registry.
- Use public map/feed access only; do not automate account portals or form submission without review.
- Review Carolina Beach Cityworks/ArcGIS terms before external reporting or redistribution.
- Treat Wrightsville Google My Maps/KML as public reference data with attribution and reasonable cadence.
