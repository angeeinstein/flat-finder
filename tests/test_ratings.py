"""Rating score calculation tests."""
import pytest

from app.extensions import db
from app.models.apartment import Apartment
from app.models.rating import ApartmentRating, RatingCategory
from app.services.scoring import (
    calculate_average_score,
    calculate_score,
    is_rating_complete,
    score_breakdown,
    seed_default_categories,
)


@pytest.fixture()
def two_categories(app, db_session):
    db.session.query(ApartmentRating).delete()
    db.session.query(RatingCategory).delete()
    cats = [
        RatingCategory(name="Price",   weight=2.0, min_score=0, max_score=10, display_order=1, is_active=True),
        RatingCategory(name="Comfort", weight=1.0, min_score=0, max_score=10, display_order=2, is_active=True),
    ]
    db.session.add_all(cats)
    db.session.commit()
    return cats


@pytest.fixture()
def apt(app, db_session):
    a = Apartment(title="Test apt")
    db.session.add(a)
    db.session.commit()
    return a


def test_no_ratings_returns_none(app, two_categories, apt, regular_user):
    assert calculate_score(apt.id, regular_user.id) is None


def test_single_category_score(app, two_categories, apt, regular_user):
    cat = two_categories[0]
    db.session.add(ApartmentRating(apartment_id=apt.id, user_id=regular_user.id,
                                   category_id=cat.id, score=8))
    db.session.commit()
    # 8/10 = 0.8 → 80
    assert calculate_score(apt.id, regular_user.id) == 80.0


def test_weighted_average(app, two_categories, apt, regular_user):
    price, comfort = two_categories
    db.session.add(ApartmentRating(apartment_id=apt.id, user_id=regular_user.id,
                                   category_id=price.id, score=10))    # weight 2
    db.session.add(ApartmentRating(apartment_id=apt.id, user_id=regular_user.id,
                                   category_id=comfort.id, score=4))   # weight 1
    db.session.commit()
    # weighted: (1.0 * 2 + 0.4 * 1) / (2+1) = 2.4/3 = 0.8 -> 80
    assert calculate_score(apt.id, regular_user.id) == 80.0


def test_partial_ratings(app, two_categories, apt, regular_user):
    """Score from rated active categories only."""
    price = two_categories[0]
    db.session.add(ApartmentRating(apartment_id=apt.id, user_id=regular_user.id,
                                   category_id=price.id, score=6))
    db.session.commit()
    assert calculate_score(apt.id, regular_user.id) == 60.0
    assert is_rating_complete(apt.id, regular_user.id) is False


def test_inactive_categories_ignored(app, two_categories, apt, regular_user):
    price, comfort = two_categories
    comfort.is_active = False
    db.session.add(ApartmentRating(apartment_id=apt.id, user_id=regular_user.id,
                                   category_id=price.id, score=5))
    db.session.add(ApartmentRating(apartment_id=apt.id, user_id=regular_user.id,
                                   category_id=comfort.id, score=10))
    db.session.commit()
    # Only Price counts: 50
    assert calculate_score(apt.id, regular_user.id) == 50.0


def test_average_score_across_users(app, two_categories, apt, regular_user, admin_user):
    cat = two_categories[0]
    db.session.add(ApartmentRating(apartment_id=apt.id, user_id=regular_user.id,
                                   category_id=cat.id, score=10))
    db.session.add(ApartmentRating(apartment_id=apt.id, user_id=admin_user.id,
                                   category_id=cat.id, score=4))
    db.session.commit()
    # personal scores: 100 and 40 → avg 70
    assert calculate_average_score(apt.id) == 70.0


def test_seed_default_categories(app, db_session):
    db.session.query(ApartmentRating).delete()
    db.session.query(RatingCategory).delete()
    db.session.commit()
    n = seed_default_categories()
    assert n > 0
    assert RatingCategory.query.count() == n
