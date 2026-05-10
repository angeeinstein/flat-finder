"""Teams blueprint: create, manage, invite, join, chat."""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from flask import (
    Blueprint, abort, flash, g, jsonify, redirect, render_template,
    request, session, url_for,
)
from flask_login import current_user, login_required

from app.extensions import db
from app.models.team import Team, TeamInvitation, TeamMember, TeamMemberRole, TeamMessage
from app.services.audit import log_action


bp = Blueprint("teams", __name__, template_folder="../templates")


def _require_team_admin(team: Team) -> None:
    if not team.is_admin(current_user.id):
        abort(403)


# ------------------------------------------------------------------ list / create

@bp.route("/")
@login_required
def index():
    from app.models.team import TeamMember as TM
    memberships = TM.query.filter_by(user_id=current_user.id).all()
    teams = [m.team for m in memberships if m.team]
    return render_template("teams/index.html", teams=teams, memberships={m.team_id: m for m in memberships})


@bp.route("/new", methods=["GET", "POST"])
@login_required
def create():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        if not name:
            flash("Team name is required.", "warning")
            return render_template("teams/create.html")
        team = Team(
            name=name,
            description=description or None,
            created_by_id=current_user.id,
        )
        db.session.add(team)
        db.session.flush()
        member = TeamMember(
            team_id=team.id,
            user_id=current_user.id,
            role=TeamMemberRole.ADMIN,
        )
        db.session.add(member)
        db.session.commit()
        log_action("team_created", target_type="Team", target_id=team.id,
                   details={"name": name})
        flash(f'Team "{name}" created.', "success")
        return redirect(url_for("teams.detail", team_id=team.id))
    return render_template("teams/create.html")


# ------------------------------------------------------------------ team detail

@bp.route("/<int:team_id>")
@login_required
def detail(team_id: int):
    team = db.session.get(Team, team_id)
    if not team:
        abort(404)
    my_member = team.get_member(current_user.id)
    if not my_member and not current_user.is_admin:
        abort(403)

    invite_link = url_for("teams.join", token=team.invite_token, _external=True)
    invitations = TeamInvitation.query.filter_by(
        team_id=team_id
    ).order_by(TeamInvitation.created_at.desc()).limit(20).all()
    messages = (
        TeamMessage.query
        .filter_by(team_id=team_id, is_deleted=False)
        .order_by(TeamMessage.created_at.asc())
        .limit(100)
        .all()
    )
    return render_template(
        "teams/detail.html",
        team=team,
        my_member=my_member,
        invite_link=invite_link,
        invitations=invitations,
        messages=messages,
        TeamMemberRole=TeamMemberRole,
    )


# ------------------------------------------------------------------ join via link/token

@bp.route("/join/<token>")
def join(token: str):
    """Public join link — works before login (login_required handled by redirect)."""
    # Try invite-link token first, then per-email invitation token
    team = Team.query.filter_by(invite_token=token).first()
    invitation: TeamInvitation | None = None
    if not team:
        invitation = TeamInvitation.query.filter_by(token=token).first()
        if not invitation or invitation.is_expired or invitation.is_used:
            flash("This invite link is invalid or has expired.", "danger")
            return redirect(url_for("main.dashboard") if current_user.is_authenticated else url_for("auth.login"))
        team = invitation.team

    if not current_user.is_authenticated:
        session["pending_join_token"] = token
        return redirect(url_for("auth.login", next=url_for("teams.join", token=token)))

    existing = team.get_member(current_user.id)
    if existing:
        flash(f'You are already a member of "{team.name}".', "info")
        return redirect(url_for("teams.detail", team_id=team.id))

    member = TeamMember(
        team_id=team.id,
        user_id=current_user.id,
        role=TeamMemberRole.MEMBER,
    )
    db.session.add(member)
    if invitation:
        invitation.accepted_at = datetime.utcnow()
    db.session.commit()
    log_action("team_joined", target_type="Team", target_id=team.id)
    flash(f'You joined "{team.name}".', "success")
    return redirect(url_for("teams.detail", team_id=team.id))


# ------------------------------------------------------------------ invite by email

@bp.route("/<int:team_id>/invite", methods=["POST"])
@login_required
def invite(team_id: int):
    team = db.session.get(Team, team_id)
    if not team:
        abort(404)
    _require_team_admin(team)
    email = request.form.get("email", "").strip().lower()
    if not email:
        flash("Email address required.", "warning")
        return redirect(url_for("teams.detail", team_id=team_id))
    inv = TeamInvitation(
        team_id=team_id,
        email=email,
        invited_by_id=current_user.id,
        expires_at=datetime.utcnow() + timedelta(days=7),
    )
    db.session.add(inv)
    db.session.commit()
    invite_url = url_for("teams.join", token=inv.token, _external=True)
    flash(f"Invitation link for {email}: {invite_url}", "success")
    return redirect(url_for("teams.detail", team_id=team_id))


# ------------------------------------------------------------------ regenerate invite link

@bp.route("/<int:team_id>/regenerate-link", methods=["POST"])
@login_required
def regenerate_link(team_id: int):
    team = db.session.get(Team, team_id)
    if not team:
        abort(404)
    _require_team_admin(team)
    team.invite_token = secrets.token_hex(32)
    db.session.commit()
    flash("Invite link regenerated.", "success")
    return redirect(url_for("teams.detail", team_id=team_id))


# ------------------------------------------------------------------ member management

@bp.route("/<int:team_id>/members/<int:user_id>/promote", methods=["POST"])
@login_required
def promote_member(team_id: int, user_id: int):
    team = db.session.get(Team, team_id)
    if not team:
        abort(404)
    _require_team_admin(team)
    member = team.get_member(user_id)
    if not member:
        abort(404)
    member.role = TeamMemberRole.ADMIN
    db.session.commit()
    flash("Member promoted to admin.", "success")
    return redirect(url_for("teams.detail", team_id=team_id))


@bp.route("/<int:team_id>/members/<int:user_id>/demote", methods=["POST"])
@login_required
def demote_member(team_id: int, user_id: int):
    team = db.session.get(Team, team_id)
    if not team:
        abort(404)
    _require_team_admin(team)
    if user_id == current_user.id:
        flash("You cannot demote yourself.", "warning")
        return redirect(url_for("teams.detail", team_id=team_id))
    # Prevent removing last admin
    admins = [m for m in team.members if m.role == TeamMemberRole.ADMIN]
    if len(admins) <= 1 and team.get_member(user_id) and team.get_member(user_id).role == TeamMemberRole.ADMIN:
        flash("Cannot demote the last admin.", "warning")
        return redirect(url_for("teams.detail", team_id=team_id))
    member = team.get_member(user_id)
    if member:
        member.role = TeamMemberRole.MEMBER
        db.session.commit()
    flash("Member demoted.", "success")
    return redirect(url_for("teams.detail", team_id=team_id))


@bp.route("/<int:team_id>/members/<int:user_id>/remove", methods=["POST"])
@login_required
def remove_member(team_id: int, user_id: int):
    team = db.session.get(Team, team_id)
    if not team:
        abort(404)
    if user_id != current_user.id:
        _require_team_admin(team)
    member = team.get_member(user_id)
    if not member:
        abort(404)
    # Prevent removing last admin
    if member.role == TeamMemberRole.ADMIN:
        admins = [m for m in team.members if m.role == TeamMemberRole.ADMIN]
        if len(admins) <= 1:
            flash("Cannot remove the last admin. Transfer ownership first.", "warning")
            return redirect(url_for("teams.detail", team_id=team_id))
    db.session.delete(member)
    db.session.commit()
    if user_id == current_user.id:
        # If we left the team and it was our active context, clear it
        if session.get("active_team_id") == team_id:
            session.pop("active_team_id", None)
        flash(f'You left "{team.name}".', "info")
        return redirect(url_for("teams.index"))
    flash("Member removed.", "success")
    return redirect(url_for("teams.detail", team_id=team_id))


# ------------------------------------------------------------------ delete team

@bp.route("/<int:team_id>/delete", methods=["POST"])
@login_required
def delete(team_id: int):
    team = db.session.get(Team, team_id)
    if not team:
        abort(404)
    _require_team_admin(team)
    name = team.name
    log_action("team_deleted", target_type="Team", target_id=team_id,
               details={"name": name}, commit=False)
    db.session.delete(team)
    db.session.commit()
    if session.get("active_team_id") == team_id:
        session.pop("active_team_id", None)
    flash(f'Team "{name}" deleted.', "success")
    return redirect(url_for("teams.index"))


# ------------------------------------------------------------------ edit team

@bp.route("/<int:team_id>/edit", methods=["GET", "POST"])
@login_required
def edit(team_id: int):
    team = db.session.get(Team, team_id)
    if not team:
        abort(404)
    _require_team_admin(team)
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        if not name:
            flash("Team name is required.", "warning")
        else:
            team.name = name
            team.description = description or None
            db.session.commit()
            flash("Team updated.", "success")
            return redirect(url_for("teams.detail", team_id=team_id))
    return render_template("teams/edit.html", team=team)


# ------------------------------------------------------------------ chat API

@bp.route("/<int:team_id>/messages", methods=["GET"])
@login_required
def get_messages(team_id: int):
    team = db.session.get(Team, team_id)
    if not team:
        abort(404)
    if not team.get_member(current_user.id) and not current_user.is_admin:
        abort(403)
    since_id = request.args.get("since", 0, type=int)
    msgs = (
        TeamMessage.query
        .filter(
            TeamMessage.team_id == team_id,
            TeamMessage.is_deleted.is_(False),
            TeamMessage.id > since_id,
        )
        .order_by(TeamMessage.created_at.asc())
        .limit(50)
        .all()
    )
    return jsonify([
        {
            "id": m.id,
            "user": m.user.username if m.user else "deleted",
            "content": m.content,
            "created_at": m.created_at.isoformat(),
            "is_own": m.user_id == current_user.id,
        }
        for m in msgs
    ])


@bp.route("/<int:team_id>/messages", methods=["POST"])
@login_required
def post_message(team_id: int):
    team = db.session.get(Team, team_id)
    if not team:
        abort(404)
    if not team.get_member(current_user.id):
        abort(403)
    data = request.get_json(silent=True) or {}
    content = (data.get("content") or "").strip()
    if not content:
        return jsonify({"error": "content required"}), 400
    if len(content) > 2000:
        return jsonify({"error": "message too long (max 2000 chars)"}), 400
    msg = TeamMessage(
        team_id=team_id,
        user_id=current_user.id,
        content=content,
    )
    db.session.add(msg)
    db.session.commit()
    return jsonify({
        "id": msg.id,
        "user": current_user.username,
        "content": msg.content,
        "created_at": msg.created_at.isoformat(),
        "is_own": True,
    }), 201


@bp.route("/<int:team_id>/messages/<int:msg_id>", methods=["DELETE"])
@login_required
def delete_message(team_id: int, msg_id: int):
    msg = db.session.get(TeamMessage, msg_id)
    if not msg or msg.team_id != team_id:
        abort(404)
    team = db.session.get(Team, team_id)
    if msg.user_id != current_user.id and not (team and team.is_admin(current_user.id)):
        abort(403)
    msg.is_deleted = True
    db.session.commit()
    return jsonify({"ok": True})
