"""Target addresses and per-apartment travel times."""
from __future__ import annotations

import enum
from datetime import datetime

from app.extensions import db


class TravelMode(str, enum.Enum):
    WALKING = "walking"
    BICYCLE = "bicycle"
    CAR = "car"
    TRANSIT = "transit"


class TargetAddress(db.Model):
    __tablename__ = "target_addresses"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    address = db.Column(db.String(500), nullable=False)
    lat = db.Column(db.Float, nullable=True)
    lng = db.Column(db.Float, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    # owner_id=NULL + team_id=NULL → global (admin-created, visible to all)
    # owner_id=X + team_id=NULL  → personal target of user X
    # team_id=Y                  → team target for team Y
    owner_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    team_id = db.Column(
        db.Integer, db.ForeignKey("teams.id", ondelete="CASCADE"), nullable=True, index=True
    )
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    owner = db.relationship("User")
    team = db.relationship("Team")


class TravelTime(db.Model):
    __tablename__ = "travel_times"

    id = db.Column(db.Integer, primary_key=True)
    apartment_id = db.Column(
        db.Integer, db.ForeignKey("apartments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_id = db.Column(
        db.Integer,
        db.ForeignKey("target_addresses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    mode = db.Column(db.Enum(TravelMode, name="travel_mode"), nullable=False)
    distance_km = db.Column(db.Float, nullable=True)
    duration_min = db.Column(db.Float, nullable=True)
    provider = db.Column(db.String(64), nullable=True)
    available = db.Column(db.Boolean, nullable=False, default=True)
    calculated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    target = db.relationship("TargetAddress")

    __table_args__ = (
        db.UniqueConstraint("apartment_id", "target_id", "mode", name="uq_travel_per_mode"),
    )
