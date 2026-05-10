"""Rating categories and per-user ratings."""
from __future__ import annotations

from datetime import datetime

from app.extensions import db


class RatingCategory(db.Model):
    __tablename__ = "rating_categories"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(500), nullable=True)
    weight = db.Column(db.Float, nullable=False, default=1.0)
    min_score = db.Column(db.Integer, nullable=False, default=0)
    max_score = db.Column(db.Integer, nullable=False, default=10)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    display_order = db.Column(db.Integer, nullable=False, default=0)
    # owner_id=NULL + team_id=NULL → global default (visible to all)
    # owner_id=X + team_id=NULL  → personal category of user X
    # team_id=Y                  → team category for team Y
    owner_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    team_id = db.Column(
        db.Integer, db.ForeignKey("teams.id", ondelete="CASCADE"), nullable=True, index=True
    )
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    owner = db.relationship("User")
    team = db.relationship("Team")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<RatingCategory {self.name} w={self.weight}>"


class ApartmentRating(db.Model):
    __tablename__ = "apartment_ratings"

    id = db.Column(db.Integer, primary_key=True)
    apartment_id = db.Column(
        db.Integer, db.ForeignKey("apartments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category_id = db.Column(
        db.Integer,
        db.ForeignKey("rating_categories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    score = db.Column(db.Float, nullable=False)
    comment = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    user = db.relationship("User")
    category = db.relationship("RatingCategory")

    __table_args__ = (
        db.UniqueConstraint("apartment_id", "user_id", "category_id", name="uq_rating_per_user"),
    )
