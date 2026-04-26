"""
Location utilities:
  - Extract city name from query string
  - Convert city → lat/lon via Nominatim (free, no API key)
  - Generate grid coordinates for full city coverage
"""
import httpx
from typing import Optional

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_HEADERS = {
    "User-Agent": "LeadsAPI/1.0 (leads-saas)"
}


def extract_location(query: str) -> Optional[str]:
    """
    Extract city from query like 'gyms in hyderabad' → 'hyderabad'
    Handles: 'in', 'near', 'at', 'around'
    """
    q = query.lower().strip()
    for keyword in [" in ", " near ", " at ", " around "]:
        if keyword in q:
            return q.split(keyword, 1)[1].strip()
    return None


async def geocode(location: str) -> Optional[dict]:
    """
    Convert location string → { lat, lon, display_name }
    Uses Nominatim (OpenStreetMap) — free, no API key needed.
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                NOMINATIM_URL,
                params={
                    "q": location,
                    "format": "json",
                    "limit": 1
                },
                headers=NOMINATIM_HEADERS
            )
            resp.raise_for_status()
            results = resp.json()
            if not results:
                return None
            r = results[0]
            return {
                "lat": float(r["lat"]),
                "lon": float(r["lon"]),
                "display_name": r.get("display_name", location)
            }
    except Exception:
        return None


def generate_grid(lat: float, lon: float, step: float = 0.05, size: int = 2) -> list[dict]:
    """
    Generate a grid of coordinates around a center point.
    step ≈ 0.05 degrees ≈ 5km
    size = 2 → 5x5 = 25 points (covers ~25km radius)
    size = 1 → 3x3 = 9 points
    size = 3 → 7x7 = 49 points
    """
    points = []
    for row in range(-size, size + 1):
        for col in range(-size, size + 1):
            points.append({
                "lat": round(lat + row * step, 6),
                "lon": round(lon + col * step, 6),
            })
    return points
