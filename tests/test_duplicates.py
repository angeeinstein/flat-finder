"""Duplicate detection tests."""
import pytest

from app.extensions import db
from app.models.apartment import Apartment
from app.models.duplicate import DuplicateCandidate
from app.models.listing import ListingSource
from app.services.duplicate import find_duplicate_candidates, score_pair


def _make_apt(**kwargs):
    apt = Apartment(**kwargs)
    db.session.add(apt)
    db.session.flush()
    return apt


def _add_source(apt, url, platform=None, external_id=None):
    src = ListingSource(apartment_id=apt.id, url=url, platform=platform,
                        external_id=external_id)
    db.session.add(src)
    return src


def test_same_external_id_high_confidence(app, db_session):
    a = _make_apt(title="Apt A", price=900, city="Wien", address="Foo 1")
    b = _make_apt(title="Apt B", price=920, city="Wien", address="Foo 2")
    _add_source(a, "https://example.at/1", platform="willhaben", external_id="123")
    _add_source(b, "https://example.at/2", platform="willhaben", external_id="123")
    db.session.flush()

    confidence, signals = score_pair(a, b)
    assert confidence >= 95
    assert "same_platform_external_id" in signals


def test_same_canonical_url_high_confidence(app, db_session):
    a = _make_apt(title="Same", city="Wien")
    b = _make_apt(title="Same", city="Wien")
    src_a = _add_source(a, "https://example.at/listing/123")
    src_b = _add_source(b, "https://other.at/proxy?x=1")
    src_a.canonical_url = "https://example.at/listing/123"
    src_b.canonical_url = "https://example.at/listing/123"
    db.session.flush()

    confidence, signals = score_pair(a, b)
    assert confidence >= 90
    assert "same_url" in signals


def test_close_coords_and_price(app, db_session):
    a = _make_apt(title="A", price=900, lat=48.21, lng=16.37, living_area_m2=55.0, rooms=2,
                  city="Wien", address="Foostr. 1")
    b = _make_apt(title="A copy", price=905, lat=48.2101, lng=16.3701, living_area_m2=55.5,
                  rooms=2, city="Wien", address="Foostr. 1")
    db.session.flush()
    confidence, signals = score_pair(a, b)
    assert "close_coordinates" in signals
    assert "similar_price" in signals
    assert "similar_area" in signals
    assert confidence >= 40


def test_different_apartments_low_confidence(app, db_session):
    a = _make_apt(title="Cozy 2-room", price=800, lat=48.21, lng=16.37,
                  living_area_m2=50.0, rooms=2, city="Wien", address="Foo 1")
    b = _make_apt(title="Industrial loft", price=2200, lat=48.30, lng=16.45,
                  living_area_m2=120.0, rooms=4, city="Wien", address="Bar 99")
    db.session.flush()
    confidence, _ = score_pair(a, b)
    assert confidence < 40


def test_find_creates_candidates(app, db_session):
    db.session.query(DuplicateCandidate).delete()

    a = _make_apt(title="X", price=900, city="Wien", address="Foostr. 1",
                  lat=48.21, lng=16.37, living_area_m2=55.0, rooms=2)
    b = _make_apt(title="X (the same)", price=900, city="Wien",
                  address="Foostr. 1", lat=48.21, lng=16.37,
                  living_area_m2=55.0, rooms=2)
    db.session.flush()

    created = find_duplicate_candidates(a)
    assert len(created) == 1
    assert created[0].confidence >= 40
