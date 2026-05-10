"""Geocoding provider abstraction."""
from __future__ import annotations

from flask import current_app

from app.services.geocoding.base import GeocodingProvider


def get_provider() -> GeocodingProvider:
    name = (current_app.config.get("GEOCODING_PROVIDER") or "nominatim").lower()
    if name == "nominatim":
        from app.services.geocoding.nominatim import NominatimProvider
        return NominatimProvider(
            user_agent=current_app.config.get("NOMINATIM_USER_AGENT", "flat-finder/1.0"),
        )
    # default fallback
    from app.services.geocoding.nominatim import NominatimProvider
    return NominatimProvider(user_agent="flat-finder/1.0")


def geocode(address: str) -> tuple[float, float] | None:
    if not address or not address.strip():
        return None
    try:
        return get_provider().geocode(address)
    except Exception:
        current_app.logger.exception("Geocoding failed")
        return None


def search(query: str, limit: int = 6) -> list[dict]:
    if not query or len(query.strip()) < 3:
        return []
    try:
        provider = get_provider()
    except Exception:
        current_app.logger.exception("Geocoding provider init failed")
        return []
    fn = getattr(provider, "search", None)
    if fn is None:
        return []
    try:
        return fn(query, limit=limit)
    except Exception:
        current_app.logger.exception("Address search failed")
        return []
