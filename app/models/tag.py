"""Apartment tags (many-to-many)."""
from __future__ import annotations

from datetime import datetime

from app.extensions import db


apartment_tags = db.Table(
    "apartment_tags",
    db.Column(
        "apartment_id",
        db.Integer,
        db.ForeignKey("apartments.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    db.Column(
        "tag_id",
        db.Integer,
        db.ForeignKey("tags.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Tag(db.Model):
    __tablename__ = "tags"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), unique=True, nullable=False)
    slug = db.Column(db.String(64), unique=True, nullable=False, index=True)
    color = db.Column(db.String(16), nullable=True, default="#6c757d")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
