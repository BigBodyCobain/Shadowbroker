# DrishX / S2 truck motion detection — third-party notice

Detection code in `backend/services/road_corridor_sat/` is adapted from:

- **DrishX** — MIT License — [sparkyniner/DRISH-X-Satellite-powered-freight-intelligence-](https://github.com/sparkyniner/DRISH-X-Satellite-powered-freight-intelligence-)
- **S2TruckDetect / Fisser et al. (2022)** — [Detecting Moving Trucks on Roads Using Sentinel-2 Data](https://ui.adsabs.harvard.edu/abs/2022RemS...14.1595F/abstract)

The trained Random Forest weights ship as `backend/data/drishx/rf_model.pickle` from the DrishX distribution.

Satellite imagery: [Copernicus Data Space Ecosystem](https://dataspace.copernicus.eu/) (free, ESA).  
Road network: [OpenStreetMap](https://www.openstreetmap.org/) via Overpass.
