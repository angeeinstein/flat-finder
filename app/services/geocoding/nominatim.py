"""Nominatim (OpenStreetMap) geocoding provider."""
from __future__ import annotations

import time

import requests

from app.services.geocoding.base import GeocodingProvider


class NominatimProvider(GeocodingProvider):
    name = "nominatim"
    BASE_URL = "https://nominatim.openstreetmap.org/search"

    def __init__(self, user_agent: str = "flat-finder/1.0"):
        self.user_agent = user_agent
        self._last_call = 0.0  # rate-limit: 1 req/sec per Nominatim policy

    def geocode(self, address: str) -> tuple[float, float] | None:
        if not address:
            return None
        # honour rate limit
        elapsed = time.time() - self._last_call
        if elapsed < 1.0:
            time.sleep(1.0 - elapsed)

        params = {"q": address, "format": "json", "limit": 1}
        headers = {"User-Agent": self.user_agent, "Accept-Language": "en"}
        try:
            r = requests.get(self.BASE_URL, params=params, headers=headers, timeout=10)
            r.raise_for_status()
            data = r.json()
        except (requests.RequestException, ValueError):
            return None
        finally:
            self._last_call = time.time()
        if not data:
            return None
        try:
            return float(data[0]["lat"]), float(data[0]["lon"])
        except (KeyError, ValueError, TypeError):
            return None
