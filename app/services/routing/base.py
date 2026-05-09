"""Routing provider interface."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class RouteResult:
    distance_km: float
    duration_min: float
    provider: str


class RoutingProvider(ABC):
    name: str = "abstract"

    @abstractmethod
    def calculate_route(
        self,
        origin_lat: float,
        origin_lng: float,
        target_lat: float,
        target_lng: float,
        mode: str,
    ) -> RouteResult | None:
        """Return route info or None if mode/route is unsupported."""
