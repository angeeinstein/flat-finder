"""Generic key/value app settings (persisted to DB, overrideable in admin UI)."""
from __future__ import annotations

from datetime import datetime

from app.extensions import db


class AppSetting(db.Model):
    __tablename__ = "app_settings"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(120), unique=True, nullable=False, index=True)
    value = db.Column(db.Text, nullable=True)
    description = db.Column(db.String(500), nullable=True)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    @classmethod
    def get(cls, key: str, default: str | None = None) -> str | None:
        row = cls.query.filter_by(key=key).first()
        return row.value if row else default

    @classmethod
    def set(cls, key: str, value: str, description: str | None = None) -> "AppSetting":
        row = cls.query.filter_by(key=key).first()
        if row:
            row.value = value
            if description is not None:
                row.description = description
        else:
            row = cls(key=key, value=value, description=description)
            db.session.add(row)
        return row
