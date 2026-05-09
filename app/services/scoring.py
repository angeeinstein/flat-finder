"""Weighted score calculation for apartments."""
from __future__ import annotations

from typing import NamedTuple

from app.extensions import db
from app.models.rating import ApartmentRating, RatingCategory


DEFAULT_CATEGORIES = [
    ("Price", "Value for money", 1.5),
    ("Location", "Neighbourhood and surroundings", 1.5),
    ("Public transport access", "Proximity to transit", 1.0),
    ("Car accessibility / parking", "Parking and road access", 0.5),
    ("Size and room layout", "Floor plan and usable space", 1.0),
    ("Building condition", "Age, state, and maintenance", 1.0),
    ("Kitchen / bathroom quality", "Wet rooms and fittings", 0.8),
    ("Noise / surroundings", "Acoustic comfort", 0.8),
    ("Balcony / garden / outdoor space", "Outdoor amenities", 0.6),
    ("Internet / work-from-home suitability", "Connectivity and quiet", 0.6),
    ("Subjective feeling", "Overall impression", 1.0),
]


class ScoreBreakdownEntry(NamedTuple):
    category_id: int
    name: str
    weight: float
    score: float | None
    normalized: float | None  # 0..1


def seed_default_categories(commit: bool = True) -> int:
    """Insert the default set of rating categories if none exist yet."""
    if RatingCategory.query.first():
        return 0
    for order, (name, desc, weight) in enumerate(DEFAULT_CATEGORIES):
        db.session.add(RatingCategory(
            name=name, description=desc, weight=weight,
            min_score=0, max_score=10,
            display_order=order, is_active=True,
        ))
    if commit:
        db.session.commit()
    return len(DEFAULT_CATEGORIES)


def calculate_score(apartment_id: int, user_id: int) -> float | None:
    """Weighted average over rated active categories, normalized to 0..100."""
    cats = RatingCategory.query.filter_by(is_active=True).all()
    if not cats:
        return None
    cat_map = {c.id: c for c in cats}

    ratings = ApartmentRating.query.filter_by(
        apartment_id=apartment_id, user_id=user_id
    ).all()
    if not ratings:
        return None

    weighted_sum = 0.0
    total_weight = 0.0
    for r in ratings:
        cat = cat_map.get(r.category_id)
        if not cat:
            continue
        span = max(1, cat.max_score - cat.min_score)
        normalized = (r.score - cat.min_score) / span  # 0..1
        weighted_sum += normalized * cat.weight
        total_weight += cat.weight
    if total_weight <= 0:
        return None
    return round((weighted_sum / total_weight) * 100, 1)


def calculate_average_score(apartment_id: int) -> float | None:
    """Average personal score across all users for an apartment."""
    user_ids = [
        u for (u,) in db.session.query(ApartmentRating.user_id)
        .filter_by(apartment_id=apartment_id).distinct().all()
    ]
    scores = [calculate_score(apartment_id, uid) for uid in user_ids]
    scores = [s for s in scores if s is not None]
    if not scores:
        return None
    return round(sum(scores) / len(scores), 1)


def score_breakdown(apartment_id: int, user_id: int) -> list[ScoreBreakdownEntry]:
    """Per-category breakdown of a user's ratings for an apartment."""
    cats = (
        RatingCategory.query.filter_by(is_active=True)
        .order_by(RatingCategory.display_order)
        .all()
    )
    rating_map = {
        r.category_id: r for r in ApartmentRating.query.filter_by(
            apartment_id=apartment_id, user_id=user_id
        ).all()
    }
    out = []
    for c in cats:
        r = rating_map.get(c.id)
        if r is None:
            out.append(ScoreBreakdownEntry(c.id, c.name, c.weight, None, None))
        else:
            span = max(1, c.max_score - c.min_score)
            normalized = (r.score - c.min_score) / span
            out.append(ScoreBreakdownEntry(c.id, c.name, c.weight, r.score, normalized))
    return out


def is_rating_complete(apartment_id: int, user_id: int) -> bool:
    cats = RatingCategory.query.filter_by(is_active=True).all()
    rated_ids = {
        r.category_id for r in ApartmentRating.query.filter_by(
            apartment_id=apartment_id, user_id=user_id
        ).all()
    }
    return all(c.id in rated_ids for c in cats)
