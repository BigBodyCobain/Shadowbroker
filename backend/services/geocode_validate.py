"""Country-bbox post-filter for geocoded results.

Any fetcher that turns a country-tagged row into a lat/lng should call
``coord_in_country()`` after the geocoder returns. If the coordinate
falls outside the country's bounding box, the result is almost
certainly a namesake collision (e.g. "Milan, WI" landing in Milan,
Italy) and the caller should reject or retry with a stronger query.

This is a cheap sanity gate that catches geocoder mistakes no human
operator will ever spot by eye across thousands of points.

Bounding boxes are deliberately generous — they include territories,
overseas islands, and a small buffer — so that legitimate coastal or
border cities are never false-rejected. Goal is to catch "wrong
continent", not "off by a few km".
"""

from __future__ import annotations

from typing import Optional, Tuple

# (min_lat, min_lng, max_lat, max_lng)
_COUNTRY_BBOX: dict[str, Tuple[float, float, float, float]] = {
    # North America
    "USA": (18.0, -180.0, 72.0, -65.0),          # inc. Alaska + Hawaii
    "Canada": (41.0, -142.0, 84.0, -52.0),
    "Mexico": (14.0, -120.0, 33.0, -86.0),
    # South & Central America
    "Brazil": (-35.0, -74.5, 6.0, -34.0),
    "Argentina": (-56.0, -74.0, -21.5, -53.0),
    "Chile": (-56.0, -76.0, -17.0, -66.0),
    "Colombia": (-5.0, -82.0, 13.5, -66.5),
    "Peru": (-19.0, -82.0, 0.5, -68.5),
    "Venezuela": (0.5, -73.5, 12.5, -59.5),
    "Ecuador": (-5.5, -92.5, 2.0, -75.0),        # inc. Galápagos
    "Bolivia": (-23.0, -69.5, -9.5, -57.5),
    "Uruguay": (-35.0, -58.5, -30.0, -53.0),
    "Paraguay": (-28.0, -63.0, -19.0, -54.0),
    "Guatemala": (13.5, -92.5, 18.0, -88.0),
    "Honduras": (12.5, -89.5, 16.5, -83.0),
    "Nicaragua": (10.5, -88.0, 15.5, -83.0),
    "Costa Rica": (8.0, -86.0, 11.5, -82.5),
    "Panama": (7.0, -83.5, 9.7, -77.0),
    "El Salvador": (13.0, -90.5, 14.5, -87.5),
    "Cuba": (19.5, -85.0, 23.5, -74.0),
    "Dominican Republic": (17.5, -72.5, 20.0, -68.0),
    "Haiti": (17.5, -74.5, 20.5, -71.5),
    "Jamaica": (17.5, -78.5, 18.7, -76.0),
    "Puerto Rico": (17.5, -68.0, 19.0, -65.0),
    # Europe
    "United Kingdom": (49.0, -9.0, 61.0, 2.5),
    "Ireland": (51.0, -11.0, 56.0, -5.0),
    "France": (41.0, -5.5, 51.5, 9.8),
    "Germany": (47.0, 5.5, 56.0, 15.5),
    "Spain": (27.0, -18.5, 44.0, 4.5),           # inc. Canary Islands
    "Portugal": (32.0, -32.0, 42.5, -6.0),       # inc. Azores + Madeira
    "Italy": (36.0, 6.5, 47.5, 19.0),
    "Netherlands": (50.5, 3.0, 53.8, 7.3),
    "Belgium": (49.4, 2.5, 51.6, 6.5),
    "Switzerland": (45.7, 5.8, 48.0, 10.6),
    "Austria": (46.3, 9.5, 49.1, 17.2),
    "Poland": (49.0, 14.0, 55.0, 24.2),
    "Czech Republic": (48.5, 12.0, 51.2, 18.9),
    "Slovakia": (47.7, 16.8, 49.7, 22.6),
    "Hungary": (45.7, 16.1, 48.6, 22.9),
    "Romania": (43.6, 20.2, 48.3, 29.7),
    "Bulgaria": (41.2, 22.3, 44.3, 28.7),
    "Greece": (34.7, 19.3, 41.8, 29.7),
    "Turkey": (35.8, 25.6, 42.2, 44.8),
    "Ukraine": (44.3, 22.1, 52.4, 40.3),
    "Belarus": (51.2, 23.1, 56.2, 32.8),
    "Russia": (41.0, 19.0, 82.0, 180.0),
    "Sweden": (55.0, 10.5, 69.1, 24.2),
    "Norway": (57.9, 4.5, 71.2, 31.1),
    "Finland": (59.7, 20.5, 70.1, 31.6),
    "Denmark": (54.5, 8.0, 57.9, 15.3),
    "Iceland": (63.3, -24.6, 66.6, -13.4),
    "Serbia": (42.2, 18.8, 46.2, 23.0),
    "Croatia": (42.3, 13.4, 46.6, 19.5),
    "Slovenia": (45.4, 13.3, 46.9, 16.7),
    "Bosnia and Herzegovina": (42.5, 15.7, 45.3, 19.7),
    "North Macedonia": (40.8, 20.4, 42.4, 23.1),
    "Albania": (39.6, 19.2, 42.7, 21.1),
    "Kosovo": (41.8, 20.0, 43.3, 21.8),
    "Moldova": (45.4, 26.6, 48.5, 30.2),
    "Lithuania": (53.8, 20.9, 56.5, 26.9),
    "Latvia": (55.6, 20.9, 58.1, 28.3),
    "Estonia": (57.5, 21.7, 59.8, 28.3),
    "Luxembourg": (49.4, 5.7, 50.2, 6.6),
    "Malta": (35.7, 14.1, 36.1, 14.7),
    "Cyprus": (34.5, 32.2, 35.8, 34.7),
    # Middle East
    "Israel": (29.4, 34.2, 33.4, 35.9),
    "Lebanon": (33.0, 35.1, 34.7, 36.7),
    "Jordan": (29.1, 34.9, 33.4, 39.4),
    "Syria": (32.3, 35.7, 37.4, 42.4),
    "Iraq": (29.0, 38.8, 37.4, 48.8),
    "Iran": (25.0, 44.0, 40.0, 63.4),
    "Saudi Arabia": (16.3, 34.5, 32.2, 55.7),
    "Yemen": (12.0, 42.5, 19.0, 54.5),
    "United Arab Emirates": (22.6, 51.5, 26.1, 56.4),
    "Oman": (16.6, 52.0, 26.4, 59.9),
    "Qatar": (24.4, 50.7, 26.2, 51.7),
    "Bahrain": (25.8, 50.4, 26.4, 50.8),
    "Kuwait": (28.5, 46.5, 30.1, 48.4),
    "Afghanistan": (29.4, 60.5, 38.5, 74.9),
    # Asia
    "India": (6.0, 68.0, 36.0, 98.0),
    "Pakistan": (23.7, 60.9, 37.1, 77.8),
    "Bangladesh": (20.6, 88.0, 26.6, 92.7),
    "Sri Lanka": (5.9, 79.5, 9.9, 82.0),
    "Nepal": (26.3, 80.0, 30.5, 88.2),
    "China": (18.0, 73.0, 54.0, 135.5),
    "Mongolia": (41.6, 87.7, 52.2, 119.9),
    "Japan": (24.0, 122.0, 46.0, 146.0),
    "South Korea": (33.1, 125.1, 38.6, 131.9),
    "North Korea": (37.7, 124.2, 43.0, 130.7),
    "Taiwan": (21.8, 119.3, 25.4, 122.1),
    "Hong Kong": (22.1, 113.8, 22.6, 114.5),
    "Vietnam": (8.2, 102.1, 23.4, 109.5),
    "Thailand": (5.6, 97.3, 20.5, 105.7),
    "Cambodia": (10.4, 102.3, 14.7, 107.7),
    "Laos": (13.9, 100.0, 22.5, 107.7),
    "Myanmar": (9.5, 92.1, 28.6, 101.2),
    "Malaysia": (0.8, 99.5, 7.5, 119.3),
    "Singapore": (1.1, 103.5, 1.5, 104.1),
    "Indonesia": (-11.1, 94.8, 6.1, 141.1),
    "Philippines": (4.5, 116.0, 21.5, 127.0),
    "Brunei": (4.0, 114.0, 5.1, 115.4),
    "Kazakhstan": (40.5, 46.4, 55.5, 87.4),
    "Uzbekistan": (37.1, 55.9, 45.6, 73.2),
    "Kyrgyzstan": (39.1, 69.2, 43.3, 80.3),
    "Tajikistan": (36.6, 67.3, 41.1, 75.2),
    "Turkmenistan": (35.1, 52.4, 42.8, 66.7),
    "Azerbaijan": (38.3, 44.7, 41.9, 50.6),
    "Armenia": (38.8, 43.4, 41.3, 46.6),
    "Georgia": (41.0, 40.0, 43.6, 46.8),
    # Oceania
    "Australia": (-44.0, 112.0, -9.0, 155.0),
    "New Zealand": (-48.0, 165.0, -33.0, 179.5),
    "Papua New Guinea": (-11.7, 140.8, -1.0, 156.0),
    "Fiji": (-21.0, 176.8, -12.4, -178.3),       # crosses antimeridian; see handling
    # Africa (selected — most common NUFORC reporters)
    "South Africa": (-35.0, 16.0, -22.0, 33.0),
    "Egypt": (21.7, 24.7, 31.7, 36.9),
    "Morocco": (27.6, -13.2, 35.9, -1.0),
    "Algeria": (18.9, -8.7, 37.1, 12.0),
    "Tunisia": (30.2, 7.5, 37.5, 11.6),
    "Libya": (19.5, 9.3, 33.2, 25.2),
    "Sudan": (8.6, 21.8, 22.2, 38.6),
    "Ethiopia": (3.4, 32.9, 14.9, 48.0),
    "Kenya": (-4.7, 33.9, 5.5, 41.9),
    "Tanzania": (-11.8, 29.3, -0.9, 40.4),
    "Uganda": (-1.5, 29.5, 4.2, 35.0),
    "Nigeria": (4.2, 2.6, 13.9, 14.7),
    "Ghana": (4.7, -3.3, 11.2, 1.2),
    "Senegal": (12.3, -17.6, 16.7, -11.3),
    "Ivory Coast": (4.3, -8.6, 10.7, -2.5),
    "Cameroon": (1.6, 8.5, 13.1, 16.2),
    "Angola": (-18.1, 11.7, -4.4, 24.1),
    "Zimbabwe": (-22.5, 25.2, -15.6, 33.1),
    "Zambia": (-18.1, 21.9, -8.2, 33.7),
    "Mozambique": (-26.9, 30.2, -10.5, 40.9),
    "Madagascar": (-25.7, 43.2, -11.9, 50.5),
    "Democratic Republic of the Congo": (-13.5, 12.2, 5.4, 31.4),
    "Rwanda": (-2.9, 28.8, -1.0, 30.9),
}

# Common aliases used in NUFORC / other data sources.
_COUNTRY_ALIASES: dict[str, str] = {
    "US": "USA",
    "U.S.": "USA",
    "U.S.A.": "USA",
    "United States": "USA",
    "United States of America": "USA",
    "America": "USA",
    "UK": "United Kingdom",
    "U.K.": "United Kingdom",
    "Britain": "United Kingdom",
    "Great Britain": "United Kingdom",
    "England": "United Kingdom",
    "Scotland": "United Kingdom",
    "Wales": "United Kingdom",
    "Northern Ireland": "United Kingdom",
    "Czechia": "Czech Republic",
    "Czechoslovakia": "Czech Republic",
    "South Korea": "South Korea",
    "Korea": "South Korea",
    "Republic of Korea": "South Korea",
    "Democratic People's Republic of Korea": "North Korea",
    "DPRK": "North Korea",
    "Russian Federation": "Russia",
    "Viet Nam": "Vietnam",
    "Côte d'Ivoire": "Ivory Coast",
    "Cote d'Ivoire": "Ivory Coast",
    "DR Congo": "Democratic Republic of the Congo",
    "DRC": "Democratic Republic of the Congo",
    "Congo-Kinshasa": "Democratic Republic of the Congo",
    "Macedonia": "North Macedonia",
    "Burma": "Myanmar",
    "Holland": "Netherlands",
}


def canonical_country(country: str) -> str:
    """Normalise a country string to its registry key."""
    if not country:
        return ""
    c = country.strip()
    return _COUNTRY_ALIASES.get(c, c)


def coord_in_country(lat: float, lng: float, country: str) -> Optional[bool]:
    """Return True if (lat, lng) is inside the country bbox, False if it
    is outside, or None if the country is unknown (cannot validate — the
    caller should treat unknown as "pass", not "fail").
    """
    try:
        lat_f = float(lat)
        lng_f = float(lng)
    except (TypeError, ValueError):
        return None
    if not (-90.0 <= lat_f <= 90.0 and -180.0 <= lng_f <= 180.0):
        return False
    c = canonical_country(country)
    bbox = _COUNTRY_BBOX.get(c)
    if bbox is None:
        return None
    min_lat, min_lng, max_lat, max_lng = bbox
    return min_lat <= lat_f <= max_lat and min_lng <= lng_f <= max_lng


def validate_geocode(
    lat: float,
    lng: float,
    country: str,
) -> bool:
    """Higher-level gate used in fetcher geocoding loops.

    Returns True if the coordinate is acceptable for the given country,
    False if it's clearly a namesake collision that should be rejected.
    Unknown countries are treated as "accept" so we don't throw away
    otherwise-good data for uncovered regions.
    """
    result = coord_in_country(lat, lng, country)
    return result is not False
