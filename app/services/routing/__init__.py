"""Routing provider abstraction."""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

from flask import current_app

from app.extensions import db
from app.models.apartment import Apartment
from app.models.location import TargetAddress, TravelMode, TravelTime
from app.services.routing.base import RouteResult, RoutingProvider


def get_provider() -> RoutingProvider:
    name = (current_app.config.get("ROUTING_PROVIDER") or "mock").lower()
    if name == "osrm":
        from app.services.routing.osrm import OSRMProvider
        return OSRMProvider(base_url=current_app.config.get("OSRM_BASE_URL") or "")
    if name in ("openrouteservice", "ors"):
        from app.services.routing.openrouteservice import OpenRouteServiceProvider
        return OpenRouteServiceProvider(
            api_key=current_app.config.get("OPENROUTESERVICE_API_KEY") or "",
        )
    from app.services.routing.mock import MockProvider
    return MockProvider()


SUPPORTED_MODES: tuple[TravelMode, ...] = (
    TravelMode.WALKING,
    TravelMode.BICYCLE,
    TravelMode.CAR,
    TravelMode.TRANSIT,
)


def calculate_for_apartment(apt: Apartment, target: TargetAddress) -> int:
    """Calculate (or refresh) travel times for an apartment / target combination.

    Returns the number of TravelTime rows written/updated.
    """
    if apt.lat is None or apt.lng is None or target.lat is None or target.lng is None:
        return 0

    provider = get_provider()
    written = 0
    for mode in SUPPORTED_MODES:
        try:
            result: RouteResult | None = provider.calculate_route(
                apt.lat, apt.lng, target.lat, target.lng, mode.value
            )
        except Exception:
            current_app.logger.exception("Routing provider failed for mode=%s", mode.value)
            result = None

        row = TravelTime.query.filter_by(
            apartment_id=apt.id, target_id=target.id, mode=mode
        ).first()
        if row is None:
            row = TravelTime(apartment_id=apt.id, target_id=target.id, mode=mode)
            db.session.add(row)

        row.calculated_at = datetime.utcnow()
        if result is None:
            row.distance_km = None
            row.duration_min = None
            row.available = False
            row.provider = provider.name
        else:
            row.distance_km = result.distance_km
            row.duration_min = result.duration_min
            row.available = True
            row.provider = result.provider
        written += 1
    return written
