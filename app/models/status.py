"""Per-user apartment status and notes."""
from __future__ import annotations

import enum
from datetime import datetime

from app.extensions import db


class StatusEnum(str, enum.Enum):
    NEW = "new"
    INTERESTING = "interesting"
    CONTACTED = "contacted"
    VIEWING_SCHEDULED = "viewing_scheduled"
    VIEWED = "viewed"
    FAVORITE = "favorite"
    REJECTED = "rejected"
    APPLIED = "applied"
    ACCEPTED = "accepted"
    ARCHIVED = "archived"

    @classmethod
    def label(cls, value: "StatusEnum | str") -> str:
        v = value.value if isinstance(value, cls) else value
        return v.replace("_", " ").title()


class UserApartmentStatus(db.Model):
    __tablename__ = "user_apartment_statuses"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    apartment_id = db.Column(
        db.Integer, db.ForeignKey("apartments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status = db.Column(
        db.Enum(StatusEnum, name="apartment_status"), nullable=False, default=StatusEnum.NEW
    )
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    user = db.relationship("User")

    __table_args__ = (
        db.UniqueConstraint("user_id", "apartment_id", name="uq_user_apt_status"),
    )


class UserApartmentNote(db.Model):
    __tablename__ = "user_apartment_notes"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    apartment_id = db.Column(
        db.Integer, db.ForeignKey("apartments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    user = db.relationship("User")
