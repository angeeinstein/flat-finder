"""Helper for writing audit log entries."""
from __future__ import annotations

from typing import Any

from flask import has_request_context, request

from app.extensions import db
from app.models.audit import AuditLog


def log_action(
    action: str,
    *,
    user_id: int | None = None,
    target_type: str | None = None,
    target_id: int | None = None,
    details: dict[str, Any] | None = None,
    commit: bool = True,
) -> AuditLog:
    ip = None
    if has_request_context():
        # request.remote_addr is already the real client IP because ProxyFix is
        # configured in create_app(). Trusting X-Forwarded-For directly here
        # would let any client inject an arbitrary value into the audit log.
        ip = request.remote_addr
        if user_id is None:
            from flask_login import current_user

            if current_user.is_authenticated:
                user_id = current_user.id

    entry = AuditLog(
        user_id=user_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        details=details,
        ip_address=ip,
    )
    db.session.add(entry)
    if commit:
        db.session.commit()
    return entry
