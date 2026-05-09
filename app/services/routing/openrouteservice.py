"""OpenRouteService routing provider."""
from __future__ import annotations

import requests

from app.services.routing.base import RouteResult, RoutingProvider


# ORS profiles
ORS_PROFILE = {
    "walking": "foot-walking",
    "bicycle": "cycling-regular",
    "car": "driving-car",
}


class OpenRouteServiceProvider(RoutingProvider):
    name = "openrouteservice"

    def __init__(self, api_key: str):
        self.api_key = api_key or ""
        self.base_url = "https://api.openrouteservice.org/v2/directions"

    def calculate_route(self, origin_lat, origin_lng, target_lat, target_lng, mode):
        if not self.api_key:
            return None
        profile = ORS_PROFILE.get(mode)
        if not profile:
            return None
        url = f"{self.base_url}/{profile}"
        body = {"coordinates": [[origin_lng, origin_lat], [target_lng, target_lat]]}
        try:
            r = requests.post(
                url,
                json=body,
                timeout=10,
                headers={
                    "Authorization": self.api_key,
                    "Accept": "application/json",
                },
            )
            r.raise_for_status()
            data = r.json()
        except (requests.RequestException, ValueError):
            return None
        try:
            summary = data["routes"][0]["summary"]
        except (KeyError, IndexError, TypeError):
            return None
        return RouteResult(
            distance_km=round(summary["distance"] / 1000.0, 2),
            duration_min=round(summary["duration"] / 60.0, 1),
            provider=self.name,
        )
