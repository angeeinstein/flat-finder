"""Apartment blueprint: detail, create, edit, gallery, history, compare."""
from __future__ import annotations

import shutil
from pathlib import Path

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.forms.apartment import ApartmentForm
from app.forms.note import NoteForm, TagForm
from app.models.apartment import Apartment
from app.models.listing import ApartmentChange, ListingSource
from app.models.location import TargetAddress, TravelMode, TravelTime
from app.models.rating import ApartmentRating, RatingCategory
from app.models.audit import AuditLog
from app.models.status import StatusEnum, UserApartmentNote, UserApartmentStatus
from app.models.tag import Tag
from app.models.user import User
from app.services.audit import log_action
from app.services.scoring import (
    calculate_average_score,
    calculate_score,
    score_breakdown,
)


bp = Blueprint("apartments", __name__, template_folder="../templates")


def _record_changes(apartment: Apartment, before: dict, after: dict, detected_by: str = "manual_edit") -> None:
    for k, v_after in after.items():
        v_before = before.get(k)
        if v_before != v_after:
            db.session.add(ApartmentChange(
                apartment_id=apartment.id,
                field_name=k,
                old_value=str(v_before) if v_before is not None else None,
                new_value=str(v_after) if v_after is not None else None,
                detected_by=detected_by,
            ))


def _form_to_apartment(form: ApartmentForm, apt: Apartment) -> dict:
    """Apply ApartmentForm fields to an Apartment, return a dict snapshot of fields."""
    direct_fields = [
        "title", "description", "price", "operating_costs", "total_monthly_cost",
        "deposit", "commission", "address", "city", "postal_code", "country",
        "address_is_approximate", "lat", "lng", "living_area_m2", "rooms",
        "floor", "building_type", "heating_type", "energy_cert_info",
        "has_balcony", "has_terrace", "has_garden", "has_parking", "has_cellar",
        "is_furnished", "available_from", "lease_duration_limited",
        "lease_duration_text", "contact_name", "contact_info", "is_offline",
    ]
    snap = {}
    for f in direct_fields:
        val = getattr(form, f).data
        setattr(apt, f, val)
        snap[f] = val
    return snap


@bp.route("/")
@login_required
def list_view():
    return redirect(url_for("main.dashboard"))


@bp.route("/new", methods=["GET", "POST"])
@login_required
def create():
    form = ApartmentForm()
    if form.validate_on_submit():
        apt = Apartment(created_by_id=current_user.id)
        _form_to_apartment(form, apt)
        db.session.add(apt)
        db.session.flush()

        if form.source_url.data:
            src = ListingSource(
                apartment_id=apt.id,
                url=form.source_url.data,
                platform=form.source_platform.data or None,
            )
            db.session.add(src)
        db.session.commit()
        log_action("apartment_created", target_type="Apartment", target_id=apt.id)
        flash("Apartment created.", "success")
        return redirect(url_for("apartments.detail", apt_id=apt.id))
    return render_template("apartments/create.html", form=form)


@bp.route("/<int:apt_id>")
@login_required
def detail(apt_id: int):
    apt = db.session.get(Apartment, apt_id)
    if not apt:
        abort(404)

    categories = (
        RatingCategory.query.filter_by(is_active=True)
        .order_by(RatingCategory.display_order, RatingCategory.id)
        .all()
    )
    my_ratings = {
        r.category_id: r
        for r in ApartmentRating.query.filter_by(apartment_id=apt_id, user_id=current_user.id).all()
    }
    breakdown = score_breakdown(apt_id, current_user.id)
    personal_score = calculate_score(apt_id, current_user.id)
    avg_score = calculate_average_score(apt_id)

    user_status = UserApartmentStatus.query.filter_by(
        user_id=current_user.id, apartment_id=apt_id
    ).first()
    notes = UserApartmentNote.query.filter_by(
        user_id=current_user.id, apartment_id=apt_id
    ).order_by(UserApartmentNote.created_at.desc()).all()

    travel_times = (
        TravelTime.query.filter_by(apartment_id=apt_id)
        .order_by(TravelTime.target_id, TravelTime.mode)
        .all()
    )
    targets = TargetAddress.query.filter_by(is_active=True).all()
    target_map = {t.id: t for t in targets}

    changes = apt.changes.limit(50).all()
    note_form = NoteForm()
    tag_form = TagForm()
    all_tags = Tag.query.order_by(Tag.name).all()

    # All users who have rated this apartment (for team score display)
    rater_ids = [
        uid for (uid,) in db.session.query(ApartmentRating.user_id)
        .filter_by(apartment_id=apt_id).distinct().all()
    ]
    raters = {u.id: u for u in User.query.filter(User.id.in_(rater_ids)).all()}
    user_scores = [
        (raters[uid], calculate_score(apt_id, uid))
        for uid in rater_ids
        if uid in raters
    ]
    user_scores.sort(key=lambda x: (x[1] is None, -(x[1] or 0)))

    # Recent activity log entries for this apartment
    activity = (
        AuditLog.query
        .filter_by(target_type="Apartment", target_id=apt_id)
        .order_by(AuditLog.created_at.desc())
        .limit(20)
        .all()
    )

    return render_template(
        "apartments/detail.html",
        apt=apt,
        categories=categories,
        my_ratings=my_ratings,
        breakdown=breakdown,
        personal_score=personal_score,
        avg_score=avg_score,
        user_status=user_status,
        StatusEnum=StatusEnum,
        notes=notes,
        travel_times=travel_times,
        target_map=target_map,
        TravelMode=TravelMode,
        changes=changes,
        note_form=note_form,
        tag_form=tag_form,
        all_tags=all_tags,
        user_scores=user_scores,
        activity=activity,
    )


@bp.route("/<int:apt_id>/edit", methods=["GET", "POST"])
@login_required
def edit(apt_id: int):
    apt = db.session.get(Apartment, apt_id)
    if not apt:
        abort(404)

    form = ApartmentForm(obj=apt)
    if form.validate_on_submit():
        before = {f: getattr(apt, f) for f in [
            "title", "price", "address", "city", "postal_code", "lat", "lng",
            "living_area_m2", "rooms", "is_offline", "available_from",
        ]}
        snap = _form_to_apartment(form, apt)
        after = {f: snap.get(f) for f in before}
        _record_changes(apt, before, after, detected_by="manual_edit")
        db.session.commit()
        log_action("apartment_edited", target_type="Apartment", target_id=apt.id)
        flash("Apartment updated.", "success")
        return redirect(url_for("apartments.detail", apt_id=apt.id))
    return render_template("apartments/edit.html", form=form, apt=apt)


@bp.route("/<int:apt_id>/delete", methods=["POST"])
@login_required
def delete(apt_id: int):
    apt = db.session.get(Apartment, apt_id)
    if not apt:
        abort(404)
    if not current_user.is_admin and apt.created_by_id != current_user.id:
        abort(403)

    title = apt.title or f"#{apt_id}"
    image_dir = Path(current_app.config["IMAGE_DIR"]) / str(apt_id)

    # Audit *before* the destructive commit so we never lose a record of the action.
    log_action(
        "apartment_deleted",
        target_type="Apartment",
        target_id=apt_id,
        details={"title": title},
        commit=False,
    )

    try:
        db.session.delete(apt)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("Apartment delete failed for %s", apt_id)
        flash(f"Could not delete apartment: {exc}", "danger")
        return redirect(url_for("apartments.detail", apt_id=apt_id))

    # Remove image files from disk only after the DB commit succeeded.
    if image_dir.exists():
        shutil.rmtree(image_dir, ignore_errors=True)

    flash(f'Apartment "{title}" deleted.', "success")
    return redirect(url_for("main.dashboard"))


@bp.route("/<int:apt_id>/notes", methods=["POST"])
@login_required
def add_note_form(apt_id: int):
    apt = db.session.get(Apartment, apt_id)
    if not apt:
        abort(404)
    form = NoteForm()
    if form.validate_on_submit():
        note = UserApartmentNote(
            user_id=current_user.id, apartment_id=apt_id, content=form.content.data
        )
        db.session.add(note)
        db.session.commit()
        flash("Note saved.", "success")
    else:
        flash("Could not save note.", "warning")
    return redirect(url_for("apartments.detail", apt_id=apt_id))


@bp.route("/<int:apt_id>/refresh", methods=["POST"])
@login_required
def refresh(apt_id: int):
    apt = db.session.get(Apartment, apt_id)
    if not apt:
        abort(404)
    sources = [s for s in apt.listing_sources if s.is_active]
    if not sources:
        flash("No active listing source to refresh.", "warning")
        return redirect(url_for("apartments.detail", apt_id=apt_id))
    from app.services.importer.jobs import enqueue_refresh

    for s in sources:
        try:
            enqueue_refresh(s.id)
        except Exception as e:
            flash(f"Could not enqueue refresh: {e}", "warning")
    flash("Refresh enqueued.", "info")
    return redirect(url_for("apartments.detail", apt_id=apt_id))


@bp.route("/<int:apt_id>/history")
@login_required
def history(apt_id: int):
    apt = db.session.get(Apartment, apt_id)
    if not apt:
        abort(404)
    changes = apt.changes.limit(500).all()
    return render_template("apartments/history.html", apt=apt, changes=changes)


@bp.route("/<int:apt_id>/gallery")
@login_required
def gallery(apt_id: int):
    apt = db.session.get(Apartment, apt_id)
    if not apt:
        abort(404)
    return render_template("apartments/gallery.html", apt=apt)


@bp.route("/compare")
@login_required
def compare():
    ids_str = request.args.get("ids", "")
    ids = []
    for token in ids_str.split(","):
        token = token.strip()
        if token.isdigit():
            ids.append(int(token))
    ids = ids[:4]
    apartments = []
    if ids:
        apartments = Apartment.query.filter(Apartment.id.in_(ids)).all()
        # preserve order
        order = {i: pos for pos, i in enumerate(ids)}
        apartments.sort(key=lambda a: order.get(a.id, 999))

    categories = (
        RatingCategory.query.filter_by(is_active=True)
        .order_by(RatingCategory.display_order)
        .all()
    )
    targets = TargetAddress.query.filter_by(is_active=True).all()

    personal_scores = {a.id: calculate_score(a.id, current_user.id) for a in apartments}
    avg_scores = {a.id: calculate_average_score(a.id) for a in apartments}

    travel: dict[tuple[int, int, str], TravelTime] = {}
    if apartments:
        rows = TravelTime.query.filter(
            TravelTime.apartment_id.in_([a.id for a in apartments])
        ).all()
        for r in rows:
            travel[(r.apartment_id, r.target_id, r.mode.value)] = r

    all_apartments = Apartment.query.order_by(Apartment.title).limit(500).all()
    return render_template(
        "apartments/compare.html",
        apartments=apartments,
        categories=categories,
        targets=targets,
        personal_scores=personal_scores,
        avg_scores=avg_scores,
        travel=travel,
        all_apartments=all_apartments,
        TravelMode=TravelMode,
    )
