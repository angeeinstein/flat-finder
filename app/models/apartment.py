"""The logical Apartment entity (independent of any external listing)."""
from __future__ import annotations

from datetime import datetime, date
from typing import Any

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON

from app.extensions import db


# Use JSONB on Postgres, JSON on SQLite (for tests)
JsonType = JSON().with_variant(JSONB(), "postgresql")


class Apartment(db.Model):
    __tablename__ = "apartments"

    id = db.Column(db.Integer, primary_key=True)

    # Basic info
    title = db.Column(db.String(500), nullable=True)
    description = db.Column(db.Text, nullable=True)

    # Pricing
    price = db.Column(db.Numeric(10, 2), nullable=True)
    operating_costs = db.Column(db.Numeric(10, 2), nullable=True)
    total_monthly_cost = db.Column(db.Numeric(10, 2), nullable=True)
    deposit = db.Column(db.Numeric(10, 2), nullable=True)
    commission = db.Column(db.Numeric(10, 2), nullable=True)
    currency = db.Column(db.String(8), nullable=True, default="EUR")

    # Address
    address = db.Column(db.String(500), nullable=True)
    city = db.Column(db.String(120), nullable=True, index=True)
    postal_code = db.Column(db.String(32), nullable=True, index=True)
    country = db.Column(db.String(120), nullable=True)
    address_is_approximate = db.Column(db.Boolean, nullable=False, default=False)
    lat = db.Column(db.Float, nullable=True)
    lng = db.Column(db.Float, nullable=True)

    # Physical
    living_area_m2 = db.Column(db.Float, nullable=True)
    rooms = db.Column(db.Float, nullable=True)
    floor = db.Column(db.String(64), nullable=True)
    building_type = db.Column(db.String(120), nullable=True)
    heating_type = db.Column(db.String(120), nullable=True)
    energy_cert_info = db.Column(db.String(255), nullable=True)

    # Amenities (booleans)
    has_balcony = db.Column(db.Boolean, nullable=True)
    has_terrace = db.Column(db.Boolean, nullable=True)
    has_garden = db.Column(db.Boolean, nullable=True)
    has_parking = db.Column(db.Boolean, nullable=True)
    has_cellar = db.Column(db.Boolean, nullable=True)
    is_furnished = db.Column(db.Boolean, nullable=True)

    # Availability / lease
    available_from = db.Column(db.Date, nullable=True)
    lease_duration_limited = db.Column(db.Boolean, nullable=True)
    lease_duration_text = db.Column(db.String(255), nullable=True)

    # LLM-extracted extras (filled in by Ollama when available; nullable)
    pets_allowed = db.Column(db.Boolean, nullable=True)
    internet_included = db.Column(db.Boolean, nullable=True)
    is_private_landlord = db.Column(db.Boolean, nullable=True)
    key_money = db.Column(db.Numeric(10, 2), nullable=True)

    # Contact
    contact_name = db.Column(db.String(255), nullable=True)
    contact_info = db.Column(db.String(500), nullable=True)

    # State
    is_offline = db.Column(db.Boolean, nullable=False, default=False, index=True)
    is_duplicate_of_id = db.Column(
        db.Integer, db.ForeignKey("apartments.id", ondelete="SET NULL"), nullable=True
    )
    is_duplicate_of = db.relationship(
        "Apartment", remote_side="Apartment.id", foreign_keys=[is_duplicate_of_id]
    )

    # Warning flags as JSON list of strings
    warning_flags = db.Column(JsonType, nullable=False, default=list)

    # Ownership / context — determines which user/team can see this apartment.
    # owner_id: the user who imported it (personal context = team_id IS NULL).
    # team_id:  set when imported in team context; NULL means personal.
    owner_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    team_id = db.Column(
        db.Integer, db.ForeignKey("teams.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

    # Timestamps
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    created_by_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_by = db.relationship("User", foreign_keys=[created_by_id])
    owner = db.relationship("User", foreign_keys="Apartment.owner_id")
    team = db.relationship("Team", foreign_keys="Apartment.team_id")

    # Relationships
    listing_sources = db.relationship(
        "ListingSource",
        backref="apartment",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    images = db.relationship(
        "ApartmentImage",
        backref="apartment",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ApartmentImage.id",
    )
    snapshots = db.relationship(
        "ApartmentSnapshot",
        backref="apartment",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )
    changes = db.relationship(
        "ApartmentChange",
        backref="apartment",
        cascade="all, delete-orphan",
        lazy="dynamic",
        order_by="ApartmentChange.changed_at.desc()",
    )
    ratings = db.relationship(
        "ApartmentRating",
        backref="apartment",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    user_statuses = db.relationship(
        "UserApartmentStatus",
        backref="apartment",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )
    user_notes = db.relationship(
        "UserApartmentNote",
        backref="apartment",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )
    travel_times = db.relationship(
        "TravelTime",
        backref="apartment",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    tags = db.relationship(
        "Tag",
        secondary="apartment_tags",
        backref="apartments",
        lazy="selectin",
    )

    # ---- Calculated metrics ----

    @property
    def primary_image(self):
        return self.images[0] if self.images else None

    @property
    def computed_total_monthly_cost(self) -> float | None:
        if self.total_monthly_cost is not None:
            return float(self.total_monthly_cost)
        parts = [self.price, self.operating_costs]
        nums = [float(p) for p in parts if p is not None]
        return sum(nums) if nums else None

    @property
    def cost_per_m2(self) -> float | None:
        total = self.computed_total_monthly_cost
        if total is None or not self.living_area_m2 or self.living_area_m2 <= 0:
            return None
        return round(total / self.living_area_m2, 2)

    @property
    def deposit_in_months(self) -> float | None:
        if not self.deposit or not self.price or float(self.price) <= 0:
            return None
        return round(float(self.deposit) / float(self.price), 2)

    @property
    def estimated_yearly_cost(self) -> float | None:
        total = self.computed_total_monthly_cost
        return round(total * 12, 2) if total is not None else None

    @property
    def estimated_first_month_cost(self) -> float | None:
        total = self.computed_total_monthly_cost
        if total is None:
            return None
        out = total
        if self.deposit:
            out += float(self.deposit)
        if self.commission:
            out += float(self.commission)
        return round(out, 2)

    @property
    def primary_source(self) -> "ListingSource | None":
        sources = sorted(self.listing_sources, key=lambda s: s.date_first_imported or datetime.min)
        return sources[0] if sources else None

    def add_warning(self, flag: str) -> None:
        flags = list(self.warning_flags or [])
        if flag not in flags:
            flags.append(flag)
            self.warning_flags = flags

    def remove_warning(self, flag: str) -> None:
        flags = [f for f in (self.warning_flags or []) if f != flag]
        self.warning_flags = flags

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Apartment {self.id} {self.title!r}>"
