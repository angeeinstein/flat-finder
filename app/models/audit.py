"""Audit log for important actions."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON

from app.extensions import db


JsonType = JSON().with_variant(JSONB(), "postgresql")


class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action = db.Column(db.String(120), nullable=False, index=True)
    target_type = db.Column(db.String(64), nullable=True)
    target_id = db.Column(db.Integer, nullable=True)
    details = db.Column(JsonType, nullable=True)
    ip_address = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

    user = db.relationship("User")
