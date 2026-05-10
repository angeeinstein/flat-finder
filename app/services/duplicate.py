"""Multi-signal duplicate detection."""
from __future__ import annotations

import math
from difflib import SequenceMatcher
from typing import Iterable

from sqlalchemy import or_

from app.extensions import db
from app.models.apartment import Apartment
from app.models.duplicate import DuplicateCandidate, DuplicateStatus
from app.models.listing import ListingSource


def _haversine_m(a_lat, a_lng, b_lat, b_lng) -> float:
    R = 6_371_000.0
    phi1, phi2 = math.radians(a_lat), math.radians(b_lat)
    dphi = math.radians(b_lat - a_lat)
    dlmb = math.radians(b_lng - a_lng)
    h = (math.sin(dphi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(h))


def _normalize_address(s: str | None) -> str:
    if not s:
        return ""
    return " ".join(s.lower().split())


def score_pair(a: Apartment, b: Apartment) -> tuple[int, list[str]]:
    """Compute a duplicate confidence score 0..100 and signal list."""
    if a.id == b.id:
        return 0, []

    confidence = 0
    signals: list[str] = []

    # Same platform + external_id (very strong)
    a_pairs = {(s.platform, s.external_id) for s in a.listing_sources if s.platform and s.external_id}
    b_pairs = {(s.platform, s.external_id) for s in b.listing_sources if s.platform and s.external_id}
    if a_pairs & b_pairs:
        confidence += 95
        signals.append("same_platform_external_id")

    # Same canonical or raw URL
    a_urls = {s.canonical_url or s.url for s in a.listing_sources}
    b_urls = {s.canonical_url or s.url for s in b.listing_sources}
    if a_urls & b_urls:
        confidence += 90
        signals.append("same_url")

    # Same normalized address
    addr_a = _normalize_address(a.address)
    addr_b = _normalize_address(b.address)
    if addr_a and addr_a == addr_b:
        confidence += 40
        signals.append("same_address")

    # Coordinates within 50m
    if all(v is not None for v in (a.lat, a.lng, b.lat, b.lng)):
        if _haversine_m(a.lat, a.lng, b.lat, b.lng) <= 50:
            confidence += 30
            signals.append("close_coordinates")

    # Same price within 5%
    if a.price and b.price:
        pa, pb = float(a.price), float(b.price)
        if pa > 0 and abs(pa - pb) / pa <= 0.05:
            confidence += 15
            signals.append("similar_price")

    # Same area within 3 m²
    if a.living_area_m2 and b.living_area_m2:
        if abs(a.living_area_m2 - b.living_area_m2) <= 3:
            confidence += 15
            signals.append("similar_area")

    # Same rooms
    if a.rooms is not None and b.rooms is not None and a.rooms == b.rooms:
        confidence += 10
        signals.append("same_rooms")

    # Title similarity
    if a.title and b.title:
        ratio = SequenceMatcher(None, a.title.lower(), b.title.lower()).ratio()
        if ratio >= 0.8:
            confidence += 10
            signals.append("similar_title")

    # Contact name match
    if a.contact_name and b.contact_name and a.contact_name.strip().lower() == b.contact_name.strip().lower():
        confidence += 10
        signals.append("same_contact")

    # Image perceptual hash similarity
    a_hashes = {i.perceptual_hash for i in a.images if i.perceptual_hash}
    b_hashes = {i.perceptual_hash for i in b.images if i.perceptual_hash}
    if a_hashes and b_hashes:
        from app.services.image import perceptual_hashes_similar

        for ah in a_hashes:
            if any(perceptual_hashes_similar(ah, bh) for bh in b_hashes):
                confidence += 10
                signals.append("similar_images")
                break

    return min(confidence, 100), signals


def _candidate_apartments(apt: Apartment) -> Iterable[Apartment]:
    """Pick a small set of likely-duplicate candidates within the same context."""
    q = Apartment.query.filter(Apartment.id != apt.id)
    # Scope to the same context: personal (owner-scoped) or team
    if apt.team_id is not None:
        q = q.filter(Apartment.team_id == apt.team_id)
    else:
        q = q.filter(
            Apartment.owner_id == apt.owner_id,
            Apartment.team_id.is_(None),
        )
    filters = []
    if apt.city:
        filters.append(Apartment.city.ilike(apt.city))
    if apt.address:
        filters.append(Apartment.address.ilike(f"%{apt.address[:60]}%"))
    if filters:
        q = q.filter(or_(*filters))
    return q.limit(200).all()


def find_duplicate_candidates(new_apt: Apartment, threshold: int = 40) -> list[DuplicateCandidate]:
    """Inspect a newly imported/edited apartment, create DuplicateCandidate rows."""
    created: list[DuplicateCandidate] = []
    for other in _candidate_apartments(new_apt):
        confidence, signals = score_pair(new_apt, other)
        if confidence < threshold:
            continue

        a_id = min(new_apt.id, other.id)
        b_id = max(new_apt.id, other.id)
        existing = DuplicateCandidate.query.filter_by(
            apartment_a_id=a_id, apartment_b_id=b_id
        ).first()
        if existing:
            if existing.status == DuplicateStatus.PENDING:
                existing.confidence = confidence
                existing.signals = signals
            continue
        cand = DuplicateCandidate(
            apartment_a_id=a_id,
            apartment_b_id=b_id,
            confidence=confidence,
            signals=signals,
            status=DuplicateStatus.PENDING,
        )
        db.session.add(cand)
        created.append(cand)
    return created


def merge_apartments(keep: Apartment, drop: Apartment) -> None:
    """Mark `drop` as duplicate of `keep`, preserving history.

    Listing sources of `drop` are reassigned to `keep` so all source URLs are kept.
    Images, snapshots, ratings, statuses, notes, travel times stay on `drop` for
    audit purposes; the dashboard hides duplicates.
    """
    if keep.id == drop.id:
        return
    # Reassign listing sources to the kept apartment
    for src in list(drop.listing_sources):
        src.apartment_id = keep.id
    drop.is_duplicate_of_id = keep.id
    drop.is_offline = True
    db.session.flush()
