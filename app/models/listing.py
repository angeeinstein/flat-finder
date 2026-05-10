"""External listing sources, images, snapshots and change history."""
from __future__ import annotations

from datetime import datetime

from app.extensions import db


class ListingSource(db.Model):
    """One external URL/platform record for an apartment."""
    __tablename__ = "listing_sources"

    id = db.Column(db.Integer, primary_key=True)
    apartment_id = db.Column(
        db.Integer, db.ForeignKey("apartments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    url = db.Column(db.String(2000), nullable=False)
    canonical_url = db.Column(db.String(2000), nullable=True, index=True)
    platform = db.Column(db.String(64), nullable=True, index=True)
    external_id = db.Column(db.String(255), nullable=True, index=True)

    date_first_imported = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    date_last_refreshed = db.Column(db.DateTime, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    last_http_status = db.Column(db.Integer, nullable=True)
    last_error = db.Column(db.String(500), nullable=True)

    __table_args__ = (
        db.Index("ix_listing_source_platform_extid", "platform", "external_id"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ListingSource {self.platform}:{self.external_id} -> apt {self.apartment_id}>"


class ApartmentImage(db.Model):
    __tablename__ = "apartment_images"

    id = db.Column(db.Integer, primary_key=True)
    apartment_id = db.Column(
        db.Integer, db.ForeignKey("apartments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    local_path = db.Column(db.String(500), nullable=False)
    thumbnail_path = db.Column(db.String(500), nullable=True)
    original_url = db.Column(db.String(2000), nullable=True)
    width = db.Column(db.Integer, nullable=True)
    height = db.Column(db.Integer, nullable=True)
    file_size = db.Column(db.Integer, nullable=True)
    perceptual_hash = db.Column(db.String(64), nullable=True, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    is_broken = db.Column(db.Boolean, nullable=False, default=False)
    is_floor_plan = db.Column(db.Boolean, nullable=False, default=False)


class ApartmentSnapshot(db.Model):
    __tablename__ = "apartment_snapshots"

    id = db.Column(db.Integer, primary_key=True)
    apartment_id = db.Column(
        db.Integer, db.ForeignKey("apartments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    listing_source_id = db.Column(
        db.Integer, db.ForeignKey("listing_sources.id", ondelete="SET NULL"), nullable=True
    )
    text_content = db.Column(db.Text, nullable=True)
    html_path = db.Column(db.String(500), nullable=True)  # path to file on disk if stored
    retrieved_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class ApartmentChange(db.Model):
    __tablename__ = "apartment_changes"

    id = db.Column(db.Integer, primary_key=True)
    apartment_id = db.Column(
        db.Integer, db.ForeignKey("apartments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    field_name = db.Column(db.String(64), nullable=False)
    old_value = db.Column(db.Text, nullable=True)
    new_value = db.Column(db.Text, nullable=True)
    changed_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    detected_by = db.Column(db.String(64), nullable=True)  # 'import' | 'manual_edit' | 'refresh'
