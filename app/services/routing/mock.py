"""Mock routing provider (haversine distance, plausible speeds)."""
from __future__ import annotations

import math

from app.services.routing.base import RouteResult, RoutingProvider


# average speeds in km/h
SPEEDS = {
    "walking": 4.8,
    "bicycle": 16.0,
    "car": 35.0,
    "transit": 25.0,
}


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * R * math.asin(math.sqrt(a))


class MockProvider(RoutingProvider):
    name = "mock"

    def calculate_route(self, origin_lat, origin_lng, target_lat, target_lng, mode):
        speed = SPEEDS.get(mode)
        if speed is None:
            return None
        # Use detour factor: routes are ~30% longer than straight line
        straight = haversine_km(origin_lat, origin_lng, target_lat, target_lng)
        distance = straight * 1.3
        duration = (distance / speed) * 60.0
        return RouteResult(
            distance_km=round(distance, 2),
            duration_min=round(duration, 1),
            provider=self.name,
        )
