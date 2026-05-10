"""AppContext — per-request tenant isolation layer.

Every apartment query MUST go through AppContext.apartment_query() so the
correct owner/team filter is always applied.  Never call Apartment.query
directly in views or the API.
"""
from __future__ import annotations

from flask import abort, session
from flask_login import current_user

from app.extensions import db
from app.models.apartment import Apartment
from app.models.job import ImportJob
from app.models.team import Team, TeamMember


class AppContext:
    """Encapsulates the active context (personal or a specific team).

    Built once per request in app.before_request and stored on flask.g.
    """

    def __init__(self, user_id: int, team_id: int | None) -> None:
        self.user_id = user_id
        self.team_id = team_id

    # ------------------------------------------------------------------ factory

    @classmethod
    def from_session(cls, user_id: int) -> "AppContext":
        """Read active_team_id from the session, re-verify membership."""
        team_id: int | None = session.get("active_team_id")
        if team_id is not None:
            still_member = TeamMember.query.filter_by(
                team_id=team_id, user_id=user_id
            ).first() is not None
            if not still_member:
                session.pop("active_team_id", None)
                team_id = None
        return cls(user_id, team_id)

    # ------------------------------------------------------------------ helpers

    @property
    def is_personal(self) -> bool:
        return self.team_id is None

    @property
    def team(self) -> Team | None:
        if self.team_id is None:
            return None
        return db.session.get(Team, self.team_id)

    def label(self) -> str:
        """Human-readable context label for templates."""
        if self.is_personal:
            return "Personal"
        t = self.team
        return t.name if t else "Team"

    # ------------------------------------------------------------------ queries

    def apartment_query(self):
        """Scoped Apartment query — the only permitted entry point."""
        if self.team_id is None:
            return Apartment.query.filter(
                Apartment.owner_id == self.user_id,
                Apartment.team_id.is_(None),
            )
        return Apartment.query.filter(Apartment.team_id == self.team_id)

    def import_job_query(self):
        """Scoped ImportJob query."""
        if self.team_id is None:
            return ImportJob.query.filter(
                ImportJob.created_by_id == self.user_id,
                ImportJob.team_id.is_(None),
            )
        return ImportJob.query.filter(ImportJob.team_id == self.team_id)

    # ------------------------------------------------------------------ guards

    def check_apartment(self, apt: Apartment) -> None:
        """Abort 403 if apt does not belong to the active context."""
        if self.team_id is None:
            ok = apt.owner_id == self.user_id and apt.team_id is None
        else:
            ok = apt.team_id == self.team_id
        if not ok:
            abort(403)

    def check_job(self, job: ImportJob) -> None:
        """Abort 403 if job does not belong to the active context."""
        if self.team_id is None:
            ok = job.created_by_id == self.user_id and job.team_id is None
        else:
            ok = job.team_id == self.team_id
        if not ok and not current_user.is_admin:
            abort(403)

    # ------------------------------------------------------------------ new-object defaults

    def apartment_defaults(self) -> dict:
        """Fields to set on a newly created Apartment for this context."""
        return {
            "owner_id": self.user_id,
            "team_id": self.team_id,
            "created_by_id": self.user_id,
        }

    def job_defaults(self) -> dict:
        """Fields to set on a newly created ImportJob for this context."""
        return {
            "created_by_id": self.user_id,
            "team_id": self.team_id,
        }
