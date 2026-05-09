"""Geocoding provider interface."""
from abc import ABC, abstractmethod


class GeocodingProvider(ABC):
    name: str = "abstract"

    @abstractmethod
    def geocode(self, address: str) -> tuple[float, float] | None:
        """Return (lat, lng) or None on failure."""
