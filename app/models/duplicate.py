"""Duplicate apartment candidate records."""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON

from app.extensions import db


JsonType = JSON().with_variant(JSONB(), "postgresql")


class DuplicateStatus(str, enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    DISMISSED = "dismissed"


class DuplicateCandidate(db.Model):
    __tablename__ = "duplicate_candidates"

    id = db.Column(db.Integer, primary_key=True)
    apartment_a_id = db.Column(
        db.Integer, db.ForeignKey("apartments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    apartment_b_id = db.Column(
        db.Integer, db.ForeignKey("apartments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    confidence = db.Column(db.Integer, nullable=False, default=0)
    signals = db.Column(JsonType, nullable=False, default=list)
    status = db.Column(
        db.Enum(DuplicateStatus, name="duplicate_status"),
        nullable=False,
        default=DuplicateStatus.PENDING,
        index=True,
    )
    reviewed_by_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

    apartment_a = db.relationship("Apartment", foreign_keys=[apartment_a_id])
    apartment_b = db.relationship("Apartment", foreign_keys=[apartment_b_id])
    reviewed_by = db.relationship("User", foreign_keys=[reviewed_by_id])

    __table_args__ = (
        db.UniqueConstraint("apartment_a_id", "apartment_b_id", name="uq_duplicate_pair"),
    )
