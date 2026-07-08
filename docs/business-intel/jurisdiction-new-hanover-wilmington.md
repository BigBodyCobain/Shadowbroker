# Jurisdiction Profile: New Hanover County / Wilmington, NC

## Identity

- Name: New Hanover County / Wilmington
- State: North Carolina
- County: New Hanover
- Primary cities/towns: Wilmington, Carolina Beach, Kure Beach, Wrightsville Beach
- Initial business categories: pools, fences, exterior projects, new-home move-in services, remodel/addition follow-up
- Registry id: `nc-new-hanover-wilmington`

## Verified Official Sources

| Source | URL | Type | Access | Initial Use |
|---|---|---|---|---|
| New Hanover Find & Download Data | https://www.nhcgov.com/1169/Find-Download-Data | Official data page | Public | Source discovery, REST directory, terms review |
| NHC REST services | https://gis.nhcgov.com/server/rest/services | ArcGIS REST directory | Public | Service discovery |
| NHC BuildingPermits | https://gis.nhcgov.com/server/rest/services/Thematic/BuildingPermits/FeatureServer | ArcGIS FeatureServer | Public query | Permit lead feed |
| NHC Parcels | https://gis.nhcgov.com/server/rest/services/Layers/Parcels/FeatureServer | ArcGIS FeatureServer | Public query | Parcel join |
| NHC DevelopmentActivity | https://gis.nhcgov.com/server/rest/services/Thematic/DevelopmentActivity/FeatureServer | ArcGIS FeatureServer | Public query | Planning/development context |
| Wilmington building permits page | https://www.wilmingtonnc.gov/Development-Business/Zoning/Building-Permits | Official reference | Public | Confirms NHC issues Wilmington building permits |
| Carolina Beach building permits page | https://www.carolinabeach.gov/256/Building-Zoning-Permits | Official reference | Public | Confirms NHC issues Carolina Beach building/trade permits |

## Source Notes

New Hanover County states that it publishes GIS services, tax information, aerial photographs, recently issued building permits, and property sales through its data resources. The BuildingPermits item describes building permits issued by New Hanover County for the current calendar year and notes that the GIS rendering is refreshed monthly.

The City of Wilmington building permit page states that New Hanover County Department of Permits & Inspections issues all building permits in Wilmington city limits. For automation, treat New Hanover County as the permit source and use Wilmington municipal boundary/city fields for filtering.

Carolina Beach has additional town permit layers beyond the county building/trade permits. Use [jurisdiction-carolina-beach-wrightsville.md](jurisdiction-carolina-beach-wrightsville.md) for the beach-town profile.

## High-Value Fields

NHC BuildingPermits layer `0` includes:

- `PERMIT_NUMBER`, `PERMIT_TYPE`, `WORK_CLASS`, `PERMIT_STATUS`
- `APPLICATION_DATE`, `ISSUE_DATE`, `LAST_INSPECTION_DATE`, `FINALED_DATE`, `EXPIRATION_DATE`
- `DESCRIPTION`, `PROJECT`, `SQUARE_FEET`, `VALUATION`
- `GENERAL_CONTRACTOR`, `PROJECT_CONTACT`
- Address parts: `NUMBER`, `STREET`, `TYPE`, `DIR`, `CITY`, `STATE`, `ZIPCODE`
- Parcel/geography: `PID`, `Lat`, `Lon`, `GEO_X`, `GEO_Y`

NHC Parcels layer includes parcel identifiers and acreage:

- `PID`, `PIN`, `MAPID`, `MAPIDKEY`, `ACRES`

## Lead Plays

1. Pool permit trigger
   - Match `PERMIT_TYPE`, `WORK_CLASS`, `DESCRIPTION`, and `PROJECT` for pool/spa/barrier terms.
   - Create implied follow-ups for fence, gate, lighting, landscaping, drainage, and maintenance.

2. New residential trigger
   - Match new construction, single-family, certificate-of-occupancy, and building-plan events.
   - Score higher when `VALUATION`, `SQUARE_FEET`, or subdivision context indicates a premium project.

3. Remodel/addition trigger
   - Match addition, remodel, porch, deck, accessory structure, patio, garage, and exterior work.
   - Link to parcel acreage and city/neighborhood.

4. Contractor activity graph
   - Group `GENERAL_CONTRACTOR` by permit type, geography, and recency.
   - Show competitors/builders that are active in specific subdivisions.

## Implementation Order

1. Import NHC BuildingPermits layer `0`.
2. Normalize address and parcel id.
3. Join NHC Parcels on `PID`.
4. Filter focus area: Wilmington plus nearby New Hanover service area.
5. Build lead scoring for pool/fence/new-home/remodel categories.
6. Add DevelopmentActivity as planning context after permit MVP is stable.

## Restrictions And Review

- Terms/commercial-use review is still required before broad automation beyond local internal analysis.
- Keep public attribution to New Hanover County GIS/permitting records in internal evidence panels.
- Avoid storing personal contact fields unless needed for an active business workflow.
