from services.data_fetcher import fetch_airports, fetch_flights, cached_airports, latest_data

fetch_airports()

# We patch logger to see what happens inside fetch_flights
import logging
logging.basicConfig(level=logging.DEBUG)

# let's run fetch_flights
fetch_flights()

flights = latest_data.get('flights', [])
print(f"Total flights: {len(flights)}")
