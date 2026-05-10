"""Admin blueprint: users, rating categories, target addresses, duplicates,
failed jobs, settings, audit log."""
from __future__ import annotations

from datetime import datetime

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.forms.admin import AppSettingForm, UserForm
from app.forms.rating import RatingCategoryForm
from app.models.apartment import Apartment
from app.models.audit import AuditLog
from app.models.duplicate import DuplicateCandidate, DuplicateStatus
from app.models.job import ImportJob, ImportJobStatus
from app.models.rating import RatingCategory
from app.models.settings import AppSetting
from app.models.user import User, UserRole
from app.services.audit import log_action
from app.services.duplicate import merge_apartments
from app.views.decorators import admin_required


bp = Blueprint("admin", __name__, template_folder="../templates")


@bp.before_request
@login_required
def _require_admin():
    if not current_user.is_admin or not current_user.is_active:
        abort(403)


# -------------------- index --------------------

@bp.route("/")
def index():
    stats = {
        "users": User.query.count(),
        "apartments": Apartment.query.count(),
        "open_duplicates": DuplicateCandidate.query.filter_by(status=DuplicateStatus.PENDING).count(),
        "failed_jobs": ImportJob.query.filter_by(status=ImportJobStatus.FAILED).count(),
        "active_categories": RatingCategory.query.filter(
            RatingCategory.owner_id.is_(None), RatingCategory.team_id.is_(None), RatingCategory.is_active.is_(True)
        ).count(),
    }
    return render_template("admin/index.html", stats=stats)


# -------------------- users --------------------

@bp.route("/users")
def users():
    users = User.query.order_by(User.username).all()
    return render_template("admin/users.html", users=users)


@bp.route("/users/new", methods=["GET", "POST"])
def user_new():
    form = UserForm()
    if form.validate_on_submit():
        if not form.password.data:
            flash("Password is required for a new user.", "warning")
        else:
            existing = User.query.filter(
                (User.username == form.username.data)
                | (User.email == form.email.data.lower())
            ).first()
            if existing:
                flash("Username or email already exists.", "danger")
            else:
                u = User(
                    username=form.username.data.strip(),
                    email=form.email.data.strip().lower(),
                    role=UserRole(form.role.data),
                    is_active=form.is_active.data,
                )
                u.set_password(form.password.data)
                db.session.add(u)
                db.session.commit()
                log_action("user_created", target_type="User", target_id=u.id,
                          details={"username": u.username})
                flash(f"Created user {u.username}.", "success")
                return redirect(url_for("admin.users"))
    return render_template("admin/user_edit.html", form=form, user=None)


@bp.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
def user_edit(user_id: int):
    u = db.session.get(User, user_id)
    if not u:
        abort(404)

    form = UserForm(obj=u)
    form.role.data = u.role.value if request.method == "GET" else form.role.data
    if form.validate_on_submit():
        # never demote the last admin
        if u.role == UserRole.ADMIN and form.role.data != "admin":
            other_admins = User.query.filter(
                User.role == UserRole.ADMIN, User.id != u.id, User.is_active.is_(True)
            ).count()
            if other_admins == 0:
                flash("Cannot demote the last admin.", "danger")
                return render_template("admin/user_edit.html", form=form, user=u)
        if u.is_active and not form.is_active.data and u.role == UserRole.ADMIN:
            other_admins = User.query.filter(
                User.role == UserRole.ADMIN, User.id != u.id, User.is_active.is_(True)
            ).count()
            if other_admins == 0:
                flash("Cannot deactivate the last admin.", "danger")
                return render_template("admin/user_edit.html", form=form, user=u)

        u.username = form.username.data.strip()
        u.email = form.email.data.strip().lower()
        u.role = UserRole(form.role.data)
        u.is_active = form.is_active.data
        if form.password.data:
            u.set_password(form.password.data)
        db.session.commit()
        log_action("user_updated", target_type="User", target_id=u.id)
        flash("User updated.", "success")
        return redirect(url_for("admin.users"))
    return render_template("admin/user_edit.html", form=form, user=u)


# -------------------- global rating category defaults (admin-only) --------------------

@bp.route("/rating-categories")
def rating_categories():
    """Manage global default categories (owner_id=NULL, team_id=NULL)."""
    cats = RatingCategory.query.filter(
        RatingCategory.owner_id.is_(None), RatingCategory.team_id.is_(None)
    ).order_by(RatingCategory.display_order, RatingCategory.id).all()
    return render_template("admin/categories.html", categories=cats)


@bp.route("/rating-categories/new", methods=["GET", "POST"])
def rating_category_new():
    form = RatingCategoryForm()
    if form.validate_on_submit():
        cat = RatingCategory(
            name=form.name.data.strip(),
            description=form.description.data or None,
            weight=form.weight.data,
            min_score=form.min_score.data,
            max_score=form.max_score.data,
            display_order=form.display_order.data,
            is_active=form.is_active.data,
            owner_id=None, team_id=None,
        )
        db.session.add(cat)
        db.session.commit()
        log_action("rating_category_created", target_type="RatingCategory", target_id=cat.id)
        flash("Global category created.", "success")
        return redirect(url_for("admin.rating_categories"))
    return render_template("admin/category_edit.html", form=form, category=None)


@bp.route("/rating-categories/<int:cat_id>/edit", methods=["GET", "POST"])
def rating_category_edit(cat_id: int):
    cat = db.session.get(RatingCategory, cat_id)
    if not cat:
        abort(404)
    form = RatingCategoryForm(obj=cat)
    if form.validate_on_submit():
        cat.name = form.name.data.strip()
        cat.description = form.description.data or None
        cat.weight = form.weight.data
        cat.min_score = form.min_score.data
        cat.max_score = form.max_score.data
        cat.display_order = form.display_order.data
        cat.is_active = form.is_active.data
        db.session.commit()
        log_action("rating_category_updated", target_type="RatingCategory", target_id=cat.id)
        flash("Category updated.", "success")
        return redirect(url_for("admin.rating_categories"))
    return render_template("admin/category_edit.html", form=form, category=cat)


@bp.route("/rating-categories/<int:cat_id>/delete", methods=["POST"])
def rating_category_delete(cat_id: int):
    cat = db.session.get(RatingCategory, cat_id)
    if not cat:
        abort(404)
    name = cat.name
    db.session.delete(cat)
    db.session.commit()
    log_action("rating_category_deleted", target_type="RatingCategory", target_id=cat_id,
               details={"name": name})
    flash(f'Category "{name}" deleted.', "success")
    return redirect(url_for("admin.rating_categories"))




# -------------------- duplicates --------------------

@bp.route("/duplicates")
def duplicates():
    page = max(1, request.args.get("page", 1, type=int))
    per_page = 30
    q = (
        DuplicateCandidate.query.filter_by(status=DuplicateStatus.PENDING)
        .order_by(DuplicateCandidate.confidence.desc())
    )
    total = q.count()
    candidates = q.offset((page - 1) * per_page).limit(per_page).all()
    total_pages = (total + per_page - 1) // per_page
    return render_template(
        "admin/duplicates.html",
        candidates=candidates,
        page=page,
        total_pages=total_pages,
    )


@bp.route("/duplicates/<int:cand_id>/confirm", methods=["POST"])
def duplicate_confirm(cand_id: int):
    cand = db.session.get(DuplicateCandidate, cand_id)
    if not cand:
        abort(404)
    keep_id = request.form.get("keep_id", type=int)
    if keep_id not in (cand.apartment_a_id, cand.apartment_b_id):
        flash("Invalid 'keep' selection.", "danger")
        return redirect(url_for("admin.duplicates"))
    drop_id = cand.apartment_b_id if keep_id == cand.apartment_a_id else cand.apartment_a_id
    keep = db.session.get(Apartment, keep_id)
    drop = db.session.get(Apartment, drop_id)
    if keep and drop:
        merge_apartments(keep, drop)
    cand.status = DuplicateStatus.CONFIRMED
    cand.reviewed_by_id = current_user.id
    cand.reviewed_at = datetime.utcnow()
    db.session.commit()
    log_action("duplicate_confirmed", target_type="DuplicateCandidate", target_id=cand.id,
              details={"kept": keep_id, "merged_from": drop_id})
    flash("Marked as duplicate and merged.", "success")
    return redirect(url_for("admin.duplicates"))


@bp.route("/duplicates/<int:cand_id>/dismiss", methods=["POST"])
def duplicate_dismiss(cand_id: int):
    cand = db.session.get(DuplicateCandidate, cand_id)
    if not cand:
        abort(404)
    cand.status = DuplicateStatus.DISMISSED
    cand.reviewed_by_id = current_user.id
    cand.reviewed_at = datetime.utcnow()
    db.session.commit()
    log_action("duplicate_dismissed", target_type="DuplicateCandidate", target_id=cand.id)
    flash("Marked as not a duplicate.", "info")
    return redirect(url_for("admin.duplicates"))


# -------------------- failed jobs --------------------

@bp.route("/failed-jobs")
def failed_jobs():
    page = max(1, request.args.get("page", 1, type=int))
    per_page = 30
    q = ImportJob.query.filter_by(status=ImportJobStatus.FAILED).order_by(ImportJob.created_at.desc())
    total = q.count()
    jobs = q.offset((page - 1) * per_page).limit(per_page).all()
    total_pages = (total + per_page - 1) // per_page
    return render_template(
        "admin/failed_jobs.html", jobs=jobs, page=page, total_pages=total_pages
    )


@bp.route("/failed-jobs/<int:job_id>/retry", methods=["POST"])
def failed_job_retry(job_id: int):
    job = db.session.get(ImportJob, job_id)
    if not job:
        abort(404)
    job.status = ImportJobStatus.PENDING
    job.error_message = None
    db.session.commit()
    try:
        from app.services.importer.jobs import enqueue_import
        enqueue_import(job.id)
    except Exception as e:
        job.status = ImportJobStatus.FAILED
        job.error_message = f"Re-enqueue failed: {e}"
        db.session.commit()
        flash(f"Could not re-enqueue: {e}", "danger")
        return redirect(url_for("admin.failed_jobs"))
    flash("Job re-enqueued.", "success")
    return redirect(url_for("admin.failed_jobs"))


# -------------------- settings --------------------

KNOWN_SETTINGS: list[dict] = [
    {
        "key": "app_name",
        "label": "App display name",
        "description": "Shown in the browser tab and navbar.",
        "type": "text",
        "default": "Flat Finder",
    },
    {
        "key": "max_images_per_listing",
        "label": "Max images per listing",
        "description": "Maximum number of photos downloaded per import (1–100).",
        "type": "number",
        "default": "30",
    },
    {
        "key": "import_http_timeout",
        "label": "Import HTTP timeout (seconds)",
        "description": "Seconds to wait when fetching a listing URL.",
        "type": "number",
        "default": "15",
    },
    {
        "key": "score_display_mode",
        "label": "Score display on dashboard",
        "description": "Which score to show on cards: your personal score or the team average.",
        "type": "select",
        "options": [("personal", "Personal (my ratings)"), ("combined", "Combined (all users' average)")],
        "default": "personal",
    },
    {
        "key": "allow_registration",
        "label": "Allow self-registration",
        "description": "Let new users sign up without an admin creating their account first.",
        "type": "bool",
        "default": "false",
    },
    {
        "key": "routing_provider",
        "label": "Routing provider",
        "description": "Backend used for travel-time calculations.",
        "type": "select",
        "options": [("mock", "Mock (straight-line estimate)"), ("osrm", "OSRM (self-hosted)"), ("openrouteservice", "OpenRouteService (API key required)")],
        "default": "mock",
    },
    {
        "key": "osrm_base_url",
        "label": "OSRM base URL",
        "description": "Base URL of your OSRM instance (only used when routing provider is OSRM).",
        "type": "text",
        "default": "",
    },
    {
        "key": "openrouteservice_api_key",
        "label": "OpenRouteService API key",
        "description": "API key for openrouteservice.org (only used when routing provider is OpenRouteService).",
        "type": "text",
        "default": "",
    },
]


@bp.route("/settings")
def settings():
    db_values = {s.key: s.value for s in AppSetting.query.all()}
    settings_with_values = [
        {**s, "value": db_values.get(s["key"], s["default"])}
        for s in KNOWN_SETTINGS
    ]
    custom = [s for s in AppSetting.query.order_by(AppSetting.key).all()
              if s.key not in {k["key"] for k in KNOWN_SETTINGS}]
    return render_template("admin/settings.html",
                           settings=settings_with_values, custom=custom)


@bp.route("/settings/save", methods=["POST"])
def settings_save():
    form = AppSettingForm()
    if form.validate_on_submit():
        AppSetting.set(form.key.data.strip(), form.value.data or "", form.description.data or None)
        db.session.commit()
        log_action("app_setting_updated", details={"key": form.key.data})
        flash("Setting saved.", "success")
    else:
        flash("Invalid form data.", "danger")
    return redirect(url_for("admin.settings"))


@bp.route("/settings/save-bulk", methods=["POST"])
def settings_save_bulk():
    known_keys = {s["key"]: s for s in KNOWN_SETTINGS}
    for key, s_def in known_keys.items():
        if s_def["type"] == "bool":
            value = "true" if request.form.get(key) == "true" else "false"
        else:
            value = request.form.get(key, "").strip()
        AppSetting.set(key, value, s_def["description"])
    db.session.commit()
    log_action("app_settings_bulk_updated", details={"keys": list(known_keys.keys())})
    flash("Settings saved.", "success")
    return redirect(url_for("admin.settings"))


@bp.route("/settings/delete", methods=["POST"])
def settings_delete():
    key = (request.form.get("key") or "").strip()
    if not key:
        flash("No key provided.", "warning")
        return redirect(url_for("admin.settings"))
    row = AppSetting.query.filter_by(key=key).first()
    if row:
        db.session.delete(row)
        db.session.commit()
        log_action("app_setting_deleted", details={"key": key})
        flash(f"Setting '{key}' deleted.", "success")
    return redirect(url_for("admin.settings"))


# -------------------- audit log --------------------

@bp.route("/audit-log")
def audit_log():
    page = max(1, request.args.get("page", 1, type=int))
    per_page = 50
    q = AuditLog.query.order_by(AuditLog.created_at.desc())
    total = q.count()
    entries = q.offset((page - 1) * per_page).limit(per_page).all()
    total_pages = (total + per_page - 1) // per_page
    return render_template(
        "admin/audit.html", entries=entries, page=page, total_pages=total_pages
    )
