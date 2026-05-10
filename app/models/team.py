"""Team, membership, invitation, and chat message models."""
from __future__ import annotations

import enum
import secrets
from datetime import datetime

from app.extensions import db


class TeamMemberRole(str, enum.Enum):
    ADMIN = "admin"
    MEMBER = "member"


class Team(db.Model):
    __tablename__ = "teams"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=True)
    # Shareable link token — anyone with this URL can join
    invite_token = db.Column(
        db.String(64), unique=True, nullable=False,
        default=lambda: secrets.token_hex(32),
    )
    created_by_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    created_by = db.relationship("User", foreign_keys=[created_by_id])
    members = db.relationship(
        "TeamMember", backref="team",
        cascade="all, delete-orphan", lazy="selectin",
    )
    messages = db.relationship(
        "TeamMessage", backref="team",
        cascade="all, delete-orphan", lazy="dynamic",
    )

    def member_count(self) -> int:
        return len(self.members)

    def get_member(self, user_id: int) -> "TeamMember | None":
        return next((m for m in self.members if m.user_id == user_id), None)

    def is_admin(self, user_id: int) -> bool:
        m = self.get_member(user_id)
        return m is not None and m.role == TeamMemberRole.ADMIN

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Team {self.id} {self.name!r}>"


class TeamMember(db.Model):
    __tablename__ = "team_members"
    __table_args__ = (
        db.UniqueConstraint("team_id", "user_id", name="uq_team_member"),
    )

    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(
        db.Integer, db.ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role = db.Column(
        db.Enum(TeamMemberRole, name="team_member_role"),
        nullable=False, default=TeamMemberRole.MEMBER,
    )
    joined_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    user = db.relationship("User", foreign_keys=[user_id], lazy="joined")


class TeamInvitation(db.Model):
    __tablename__ = "team_invitations"

    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(
        db.Integer, db.ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email = db.Column(db.String(254), nullable=True)
    token = db.Column(
        db.String(64), unique=True, nullable=False,
        default=lambda: secrets.token_hex(32),
    )
    invited_by_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=True)
    accepted_at = db.Column(db.DateTime, nullable=True)

    team = db.relationship("Team", foreign_keys=[team_id])
    invited_by = db.relationship("User", foreign_keys=[invited_by_id])

    @property
    def is_used(self) -> bool:
        return self.accepted_at is not None

    @property
    def is_expired(self) -> bool:
        return self.expires_at is not None and datetime.utcnow() > self.expires_at


class TeamMessage(db.Model):
    __tablename__ = "team_messages"

    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(
        db.Integer, db.ForeignKey("teams.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, index=True
    )
    is_deleted = db.Column(db.Boolean, nullable=False, default=False)

    user = db.relationship("User", foreign_keys=[user_id], lazy="joined")
