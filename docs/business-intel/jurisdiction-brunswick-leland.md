# Jurisdiction Profile: Brunswick County / Leland, NC

## Identity

- Name: Brunswick County / Leland
- State: North Carolina
- County: Brunswick
- Primary focus: Leland, Belville, Navassa, northern Brunswick growth corridors
- Secondary areas: Southport, Oak Island, Shallotte, Bolivia
- Initial business categories: pools, fences, new-home move-in services, exterior projects, storm response
- Registry id: `nc-brunswick-leland`

## Verified Official Sources

| Source | URL | Type | Access | Initial Use |
|---|---|---|---|---|
| Brunswick GIS, Maps & Data | https://www.brunswickcountync.gov/876/GIS-Maps-Data | Official GIS page | Public | Source discovery |
| Brunswick Data Download | https://www.brunswickcountync.gov/321/Data-Download | Official data page | Public | Open GIS portal routing |
| Brunswick Open Data | https://data-brunsco.opendata.arcgis.com/ | ArcGIS Hub | Public | Source discovery |
| Brunswick Permit Locations | https://services1.arcgis.com/W6gamXPYQeLXrdAd/arcgis/rest/services/Permit_Locations/FeatureServer | ArcGIS FeatureServer | Public query | Main permit lead feed |
| Brunswick Monthly Permit Locations | https://services1.arcgis.com/W6gamXPYQeLXrdAd/arcgis/rest/services/Monthly_Permit_Locations/FeatureServer | ArcGIS FeatureServer | Public query | Delta/refresh check |
| Brunswick Tax Parcels | https://bcgis.brunswickcountync.gov/arcgis/rest/services/Layers/TaxParcels/MapServer/0 | ArcGIS MapServer layer | Public query | Parcel/context join |
| Brunswick Research Tools | https://www.brunswickcountync.gov/202/Research-Tools | Official permit tools page | Public | Manual verification |
| Leland Permitting & Inspections | https://www.townofleland.com/planning-inspections/permitting-inspections | Official reference | Public | Leland permit routing |
| Leland Online Maps and GIS | https://www.townofleland.com/planning-inspections/online-maps-and-gis | Official GIS page | Public reference | Leland planning context |

## Source Notes

Brunswick County's Research Tools page links to a Spatial Search tool, Permit Locations Dashboard, Brunswick County Permit Portal, permit reports, and permit search. The open-data portal exposes a public `Permit Locations` FeatureServer described as a point layer containing Brunswick County permitting data, plus `Monthly Permit Locations` for previous-month changes.

Town of Leland's permitting page routes applications and inspections through an Infovision/Evolve portal. That portal requires an account, so it should remain manual verification until terms and authorization are reviewed.

Town of Leland's GIS page is useful for Development Activity, Zoning, Land Characteristics, Flood Zones, Annexations, Active Stormwater Permits, Future Land Use, and Town Limits. The page also states that recipients may not copy, sell, or otherwise redistribute town GIS data without prior written consent. Treat Leland town GIS as internal-reference-only until permission/terms are resolved.

## High-Value Fields

Brunswick Permit Locations includes:

- `ProjectNumber`, `PermitNumber`, `ProjectType`, `ProjectCategory`
- `PemitProjectStatus`, `PermitType`, `PermitStatus`
- `Description`, `SubContractor`, `PermitAmount`
- `Jurisdiction`, `ParcelAddress`, `ParcelID`
- `EstimatedRetailValue`, `PermitMonth`, `PermitYear`, `DateIssued`
- `xCoordinate`, `yCoordinate`

Brunswick Monthly Permit Locations uses the same core shape but spells project status as `PermitProjectStatus`.

Brunswick Tax Parcels includes:

- `ParcelNumber`, `PIN`, `CALCAC`, `DeedAcreage`, `TaxYear`
- `LegalDescription`, `Zoning`, `UseCode`, `ActualYearBuilt`, `DeedDate`
- Owner/mailing fields such as `Name1`, `Name2`, and address fields

## Lead Plays

1. Leland growth corridor radar
   - Filter Brunswick permit feeds where `Jurisdiction` or address context indicates Leland, Belville, Navassa, or nearby northern Brunswick.
   - Use parcel acreage, year built, zoning, and permit category to score exterior-project fit.

2. Pool and fence permit chain
   - Match `PermitType`, `ProjectType`, `ProjectCategory`, and `Description` for pool/spa/barrier/fence/gate terms.
   - Create next-best actions for fence, gate, lighting, landscaping, drainage, and maintenance.

3. New home and subdivision activity
   - Match new residential, single-family, certificate-of-occupancy, and high estimated retail value.
   - Use parcel layer and Leland development maps as context.

4. Monthly change detection
   - Use `Monthly Permit Locations` as a lightweight delta source.
   - Compare against full `Permit Locations` to catch newly issued or status-changed permits.

5. Competitor/contractor activity
   - Group `SubContractor` by permit category, jurisdiction, month, and lead type.
   - Avoid private-person profiling; focus on public business/contractor activity and permit context.

## Implementation Order

1. Import Brunswick Permit Locations.
2. Normalize permit status, type/category, address, parcel id, and issue date.
3. Add Leland-focused filtering by `Jurisdiction`, address, and town limits reference.
4. Join Brunswick Tax Parcels while minimizing owner/mailing fields.
5. Add Monthly Permit Locations as a delta/staleness check.
6. Use Leland permit portal and GIS maps as manual verification/reference until terms allow automated ingestion.

## Restrictions And Review

- Review Brunswick open-data terms before external reporting or resale.
- Do not automate Leland credentialed permit portal access without explicit authorization and terms review.
- Do not bulk copy or redistribute Leland GIS layers without prior written consent.
- Owner/mailing fields in Brunswick parcel data should be treated as sensitive and minimized by default.
