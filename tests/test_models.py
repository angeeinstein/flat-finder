"""Tests for apartment metric calculations and routing."""
from app.extensions import db
from app.models.apartment import Apartment
from app.services.routing.mock import MockProvider, haversine_km


def test_total_monthly_cost_explicit(app, db_session):
    a = Apartment(price=900, operating_costs=100, total_monthly_cost=950)
    db.session.add(a); db.session.commit()
    assert a.computed_total_monthly_cost == 950


def test_total_monthly_cost_derived(app, db_session):
    a = Apartment(price=900, operating_costs=100)
    db.session.add(a); db.session.commit()
    assert a.computed_total_monthly_cost == 1000


def test_cost_per_m2(app, db_session):
    a = Apartment(price=900, operating_costs=100, living_area_m2=50.0)
    db.session.add(a); db.session.commit()
    assert a.cost_per_m2 == 20.0


def test_deposit_in_months(app, db_session):
    a = Apartment(price=900, deposit=2700)
    db.session.add(a); db.session.commit()
    assert a.deposit_in_months == 3.0


def test_estimated_first_month(app, db_session):
    a = Apartment(price=900, operating_costs=100, deposit=2000, commission=900)
    db.session.add(a); db.session.commit()
    # total = 1000, plus deposit + commission
    assert a.estimated_first_month_cost == 3900.0


def test_warning_flags_helpers(app, db_session):
    a = Apartment(title="t", warning_flags=[])
    db.session.add(a); db.session.commit()
    a.add_warning("missing_address")
    a.add_warning("missing_address")  # duplicate ignored
    assert a.warning_flags == ["missing_address"]
    a.add_warning("no_photos")
    assert sorted(a.warning_flags) == ["missing_address", "no_photos"]
    a.remove_warning("missing_address")
    assert a.warning_flags == ["no_photos"]


def test_haversine_known_distance():
    # Wien Karlsplatz ↔ Stephansplatz ≈ 1.4 km
    d = haversine_km(48.2007, 16.3698, 48.2082, 16.3725)
    assert 0.5 < d < 2.5


def test_mock_provider_walking():
    p = MockProvider()
    r = p.calculate_route(48.21, 16.37, 48.21, 16.38, "walking")
    assert r is not None
    assert r.provider == "mock"
    assert r.distance_km > 0
    assert r.duration_min > 0


def test_mock_provider_unknown_mode_returns_none():
    p = MockProvider()
    assert p.calculate_route(48.21, 16.37, 48.21, 16.38, "teleport") is None
