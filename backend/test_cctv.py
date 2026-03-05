from services.cctv_pipeline import init_db, TFLJamCamIngestor, LTASingaporeIngestor

init_db()
print("Initialized DB")

tfl = TFLJamCamIngestor()
print(f"TFL Cameras: {len(tfl.fetch_data())}")

nyc = LTASingaporeIngestor()
print(f"SGP Cameras: {len(nyc.fetch_data())}")
