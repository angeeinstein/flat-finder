"""Background import job records."""
from __future__ import annotations

import enum
from datetime import datetime

from app.extensions import db


class ImportJobStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class ImportJob(db.Model):
    __tablename__ = "import_jobs"

    id = db.Column(db.Integer, primary_key=True)
    url = db.Column(db.String(2000), nullable=False)
    status = db.Column(
        db.Enum(ImportJobStatus, name="import_job_status"),
        nullable=False,
        default=ImportJobStatus.PENDING,
        index=True,
    )
    error_message = db.Column(db.Text, nullable=True)
    apartment_id = db.Column(
        db.Integer, db.ForeignKey("apartments.id", ondelete="SET NULL"), nullable=True
    )
    listing_source_id = db.Column(
        db.Integer, db.ForeignKey("listing_sources.id", ondelete="SET NULL"), nullable=True
    )
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    started_at = db.Column(db.DateTime, nullable=True)
    finished_at = db.Column(db.DateTime, nullable=True)
    created_by_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    team_id = db.Column(
        db.Integer, db.ForeignKey("teams.id", ondelete="SET NULL"), nullable=True, index=True
    )

    apartment = db.relationship("Apartment", foreign_keys=[apartment_id])
    listing_source = db.relationship("ListingSource", foreign_keys=[listing_source_id])
    created_by = db.relationship("User", foreign_keys=[created_by_id])
    team = db.relationship("Team", foreign_keys=[team_id])
