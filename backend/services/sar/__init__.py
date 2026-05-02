"""ShadowBroker SAR (Synthetic Aperture Radar) layer.

Two operating modes:

* **Mode A — Catalog ingest** (default-on, free, no account):
  Hits ASF Search for Sentinel-1 scene metadata over operator-defined AOIs.
  Disk footprint comparable to the earthquake layer (a few MB).

* **Mode B — Pre-processed anomaly ingest** (opt-in, free, needs account):
  Pulls already-computed deformation, flood, water-mask, and damage products
  from NASA OPERA, Copernicus EGMS, Global Flood Monitoring, Copernicus EMS,
  and UNOSAT.  No local DSP, no GPU, no 2TB cache.

Anomalies emitted by this layer are signed events through the existing
mesh signing path so other nodes can verify their provenance.
"""

from services.sar.sar_aoi import (  # noqa: F401
    SarAoi,
    bbox_for_aoi,
    load_aois,
)
from services.sar.sar_normalize import (  # noqa: F401
    ANOMALY_KINDS,
    SarAnomaly,
    SarScene,
    canonical_anomaly_json,
    evidence_hash_for_payload,
)
