"""Main blueprint: dashboard, search, import URL form, job status."""
from __future__ import annotations

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_

from app.extensions import db
from app.forms.apartment import ApartmentSearchForm, ImportURLForm
from app.models.apartment import Apartment
from app.models.job import ImportJob, ImportJobStatus
from app.models.location import TargetAddress, TravelTime, TravelMode
from app.models.rating import RatingCategory
from app.models.status import StatusEnum, UserApartmentStatus
from app.services.scoring import calculate_score, calculate_average_score
from app.services.ssrf import SSRFError, validate_import_url


bp = Blueprint("main", __name__, template_folder="../templates")


@bp.route("/")
@login_required
def dashboard():
    form = ApartmentSearchForm(request.args, meta={"csrf": False})

    q = g.ctx.apartment_query()
    # Filters
    if form.q.data:
        like = f"%{form.q.data.lower()}%"
        q = q.filter(or_(
            db.func.lower(Apartment.title).like(like),
            db.func.lower(Apartment.description).like(like),
            db.func.lower(Apartment.address).like(like),
            db.func.lower(Apartment.city).like(like),
        ))
    if form.min_price.data:
        q = q.filter(Apartment.price >= form.min_price.data)
    if form.max_price.data:
        q = q.filter(Apartment.price <= form.max_price.data)
    if form.min_area.data:
        q = q.filter(Apartment.living_area_m2 >= form.min_area.data)
    if form.max_area.data:
        q = q.filter(Apartment.living_area_m2 <= form.max_area.data)
    if form.min_rooms.data:
        q = q.filter(Apartment.rooms >= form.min_rooms.data)
    if form.city.data:
        q = q.filter(db.func.lower(Apartment.city) == form.city.data.lower())
    if form.has_balcony.data:
        q = q.filter(Apartment.has_balcony.is_(True))
    if form.has_parking.data:
        q = q.filter(Apartment.has_parking.is_(True))
    if form.online_only.data:
        q = q.filter(Apartment.is_offline.is_(False))

    # Sort
    sort = form.sort.data or "newest"
    sort_map = {
        "newest": Apartment.created_at.desc(),
        "price_asc": Apartment.price.asc().nullslast(),
        "price_desc": Apartment.price.desc().nullslast(),
        "area_desc": Apartment.living_area_m2.desc().nullslast(),
        "rooms_desc": Apartment.rooms.desc().nullslast(),
    }
    q = q.order_by(sort_map.get(sort, sort_map["newest"]))

    page = max(1, request.args.get("page", 1, type=int))
    per_page = 24
    total = q.count()
    apartments = q.offset((page - 1) * per_page).limit(per_page).all()

    personal_scores: dict[int, float | None] = {}
    avg_scores: dict[int, float | None] = {}
    statuses: dict[int, StatusEnum | None] = {}
    for a in apartments:
        personal_scores[a.id] = calculate_score(a.id, current_user.id)
        avg_scores[a.id] = calculate_average_score(a.id)
        st = UserApartmentStatus.query.filter_by(user_id=current_user.id, apartment_id=a.id).first()
        statuses[a.id] = st.status if st else None

    targets = TargetAddress.query.filter_by(is_active=True).order_by(TargetAddress.name).all()
    selected_target_id = request.args.get("target_id", type=int)

    travel_for: dict[int, dict] = {}
    if selected_target_id and apartments:
        ids = [a.id for a in apartments]
        rows = TravelTime.query.filter(
            TravelTime.target_id == selected_target_id,
            TravelTime.apartment_id.in_(ids),
        ).all()
        for r in rows:
            travel_for.setdefault(r.apartment_id, {})[r.mode.value] = r

    total_pages = (total + per_page - 1) // per_page

    _filter_keys = ["q", "min_price", "max_price", "min_area", "max_area",
                    "min_rooms", "city", "has_balcony", "has_parking", "online_only", "target_id"]
    is_filtered = any(request.args.get(k) for k in _filter_keys)

    return render_template(
        "main/dashboard.html",
        apartments=apartments,
        form=form,
        personal_scores=personal_scores,
        avg_scores=avg_scores,
        statuses=statuses,
        targets=targets,
        selected_target_id=selected_target_id,
        travel_for=travel_for,
        page=page,
        total_pages=total_pages,
        total=total,
        is_filtered=is_filtered,
    )


@bp.route("/import", methods=["GET", "POST"])
@login_required
def import_url():
    form = ImportURLForm()
    if form.validate_on_submit():
        from app.services.importer.jobs import enqueue_import

        urls = [u.strip() for u in form.urls.data.splitlines() if u.strip()]
        created_jobs = []
        for url in urls:
            try:
                clean_url = validate_import_url(url)
            except SSRFError as e:
                flash(f"Skipped {url}: {e}", "warning")
                continue
            job = ImportJob(
                url=clean_url,
                status=ImportJobStatus.PENDING,
                **g.ctx.job_defaults(),
            )
            db.session.add(job)
            db.session.flush()
            created_jobs.append(job.id)
            db.session.commit()
            try:
                enqueue_import(job.id)
            except Exception as e:
                job.error_message = f"Could not enqueue: {e}"
                job.status = ImportJobStatus.FAILED
                db.session.commit()
                flash(
                    f"Job created for {url} but the background worker is unavailable: {e}",
                    "warning",
                )

        if not created_jobs:
            flash("No URLs were imported.", "info")
            return redirect(url_for("main.import_url"))

        if len(created_jobs) == 1:
            return redirect(url_for("main.job_status", job_id=created_jobs[0]))
        flash(f"Started {len(created_jobs)} import jobs.", "success")
        return redirect(url_for("main.import_url"))

    recent_jobs = (
        g.ctx.import_job_query()
        .order_by(ImportJob.created_at.desc())
        .limit(20)
        .all()
    )
    return render_template("main/import.html", form=form, recent_jobs=recent_jobs)


@bp.route("/jobs/<int:job_id>")
@login_required
def job_status(job_id: int):
    job = db.session.get(ImportJob, job_id)
    if not job:
        abort(404)
    g.ctx.check_job(job)
    return render_template("main/job_status.html", job=job)


@bp.route("/jobs/<int:job_id>/delete", methods=["POST"])
@login_required
def delete_job(job_id: int):
    job = db.session.get(ImportJob, job_id)
    if not job:
        abort(404)
    g.ctx.check_job(job)
    if job.status == ImportJobStatus.RUNNING:
        flash("Cannot delete a running job.", "warning")
        return redirect(url_for("main.job_status", job_id=job_id))
    db.session.delete(job)
    db.session.commit()
    flash("Job deleted.", "success")
    return redirect(url_for("main.import_url"))


@bp.route("/context/switch", methods=["POST"])
@login_required
def switch_context():
    from flask import session
    from app.models.team import TeamMember

    team_id_str = request.form.get("team_id", "").strip()
    if not team_id_str:
        session.pop("active_team_id", None)
    else:
        try:
            team_id = int(team_id_str)
        except ValueError:
            abort(400)
        # Verify membership before accepting
        member = TeamMember.query.filter_by(
            team_id=team_id, user_id=current_user.id
        ).first()
        if not member:
            abort(403)
        session["active_team_id"] = team_id

    next_url = request.referrer or url_for("main.dashboard")
    return redirect(next_url)
