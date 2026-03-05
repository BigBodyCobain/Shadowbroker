import sys
import logging
logging.basicConfig(level=logging.DEBUG)

# Add backend directory to sys path so we can import modules
sys.path.append(r'f:\Codebase\Oracle\live-risk-dashboard\backend')

from services.data_fetcher import fetch_flights, latest_data

print("Testing fetch_flights...")
try:
    fetch_flights()
    print("Commercial flights count:", len(latest_data.get('commercial_flights', [])))
    print("Private jets count:", len(latest_data.get('private_jets', [])))
except Exception as e:
    import traceback
    traceback.print_exc()
