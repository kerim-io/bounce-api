import math
from core.config import settings


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate distance between two points on Earth in kilometers
    """
    R = 6371  # Earth radius in km

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = math.sin(delta_phi/2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

    return R * c


def is_in_basel_area(latitude: float, longitude: float) -> bool:
    """
    Check if coordinates are within Art Basel Miami area
    """
    distance = haversine_distance(
        settings.BASEL_LAT,
        settings.BASEL_LON,
        latitude,
        longitude
    )
    return distance <= settings.BASEL_RADIUS_KM


def get_launch_cities() -> list:
    """
    Parse LAUNCH_CITIES ("name:lat,lon,radius_km;...") plus the legacy BASEL_* center.
    Malformed entries are skipped rather than crashing on config.
    """
    cities = []
    for entry in (settings.LAUNCH_CITIES or "").split(";"):
        entry = entry.strip()
        if not entry:
            continue
        try:
            name, coords = entry.split(":", 1)
            lat_s, lon_s, radius_s = coords.split(",")
            cities.append({
                "name": name.strip(),
                "lat": float(lat_s),
                "lon": float(lon_s),
                "radius_km": float(radius_s),
            })
        except ValueError:
            continue
    cities.append({
        "name": "basel",
        "lat": settings.BASEL_LAT,
        "lon": settings.BASEL_LON,
        "radius_km": settings.BASEL_RADIUS_KM,
    })
    return cities


def nearest_launch_city(latitude: float, longitude: float) -> tuple:
    """Return (city, distance_km) for the launch city nearest to the given point."""
    best = None
    best_dist = float("inf")
    for city in get_launch_cities():
        dist = haversine_distance(latitude, longitude, city["lat"], city["lon"])
        if dist < best_dist:
            best, best_dist = city, dist
    return best, best_dist
