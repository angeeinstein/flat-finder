"""OSRM routing provider (HTTP)."""
from __future__ import annotations

import requests

from app.services.routing.base import RouteResult, RoutingProvider


# OSRM modes: car, bike, foot. No public-transit support.
OSRM_PROFILE = {
    "car": "car",
    "bicycle": "bike",
    "walking": "foot",
}


class OSRMProvider(RoutingProvider):
    name = "osrm"

    def __init__(self, base_url: str):
        self.base_url = (base_url or "").rstrip("/")

    def calculate_route(self, origin_lat, origin_lng, target_lat, target_lng, mode):
        if not self.base_url:
            return None
        profile = OSRM_PROFILE.get(mode)
        if not profile:
            return None  # OSRM has no transit
        url = (
            f"{self.base_url}/route/v1/{profile}/"
            f"{origin_lng},{origin_lat};{target_lng},{target_lat}"
            "?overview=false"
        )
        try:
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            data = r.json()
        except (requests.RequestException, ValueError):
            return None
        if data.get("code") != "Ok" or not data.get("routes"):
            return None
        route = data["routes"][0]
        return RouteResult(
            distance_km=round(route["distance"] / 1000.0, 2),
            duration_min=round(route["duration"] / 60.0, 1),
            provider=self.name,
        )
