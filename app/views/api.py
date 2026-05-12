"""JSON API blueprint."""
from __future__ import annotations

from datetime import datetime

from flask import Blueprint, abort, g, jsonify, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models.apartment import Apartment
from app.models.duplicate import DuplicateCandidate, DuplicateStatus
from app.models.job import ImportJob, ImportJobStatus
from app.models.location import TargetAddress, TravelMode, TravelTime
from app.models.rating import ApartmentRating, RatingCategory
from app.models.status import StatusEnum, UserApartmentNote, UserApartmentStatus
from app.models.tag import Tag
from app.services.audit import log_action
from app.services.scoring import (
    calculate_average_score,
    calculate_score,
)


bp = Blueprint("api", __name__, template_folder="../templates")


@bp.before_request
@login_required
def _requires_login():
    pass


# -------------------- import jobs --------------------

@bp.route("/jobs/<int:job_id>")
def job_status(job_id: int):
    job = db.session.get(ImportJob, job_id)
    if not job:
        abort(404)
    g.ctx.check_job(job)
    return jsonify({
        "id": job.id,
        "url": job.url,
        "status": job.status.value,
        "error_message": job.error_message,
        "apartment_id": job.apartment_id,
        "apartment_url": (
            url_for("apartments.detail", apt_id=job.apartment_id) if job.apartment_id else None
        ),
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    })


# -------------------- map markers --------------------

@bp.route("/map/markers")
def map_markers():
    color_by = request.args.get("color_by", "score")
    target_id = request.args.get("target_id", type=int)
    mode = request.args.get("mode", "car")

    apartments = g.ctx.apartment_query().filter(
        Apartment.lat.isnot(None), Apartment.lng.isnot(None)
    ).all()

    travel_lookup: dict[int, TravelTime] = {}
    if target_id:
        try:
            mode_enum = TravelMode(mode)
        except ValueError:
            mode_enum = TravelMode.CAR
        rows = TravelTime.query.filter(
            TravelTime.target_id == target_id,
            TravelTime.mode == mode_enum,
            TravelTime.apartment_id.in_([a.id for a in apartments]),
        ).all()
        travel_lookup = {r.apartment_id: r for r in rows}

    features = []
    for apt in apartments:
        score = calculate_score(apt.id, current_user.id) or calculate_average_score(apt.id)
        st = UserApartmentStatus.query.filter_by(
            user_id=current_user.id, apartment_id=apt.id
        ).first()
        tt = travel_lookup.get(apt.id)
        thumb = apt.primary_image
        features.append({
            "id": apt.id,
            "lat": apt.lat,
            "lng": apt.lng,
            "title": apt.title or f"Apartment #{apt.id}",
            "city": apt.city,
            "address": apt.address,
            "price": float(apt.price) if apt.price is not None else None,
            "total": apt.computed_total_monthly_cost,
            "area": apt.living_area_m2,
            "rooms": apt.rooms,
            "cost_per_m2": apt.cost_per_m2,
            "has_balcony": apt.has_balcony,
            "has_terrace": apt.has_terrace,
            "has_garden": apt.has_garden,
            "has_parking": apt.has_parking,
            "score": round(score, 1) if score is not None else None,
            "status": st.status.value if st else None,
            "warnings": apt.warning_flags or [],
            "is_offline": apt.is_offline,
            "thumbnail_url": (
                url_for("api.image_thumbnail", image_id=thumb.id) if thumb else None
            ),
            "detail_url": url_for("apartments.detail", apt_id=apt.id),
            "travel_time_min": tt.duration_min if tt else None,
            "travel_distance_km": tt.distance_km if tt else None,
        })

    targets = g.ctx.target_query().all()
    target_features = [
        {"id": t.id, "name": t.name, "lat": t.lat, "lng": t.lng, "address": t.address}
        for t in targets if t.lat is not None and t.lng is not None
    ]
    return jsonify({"apartments": features, "targets": target_features, "color_by": color_by})


@bp.route("/images/<int:image_id>/thumbnail")
def image_thumbnail(image_id: int):
    """Serve a thumbnail. Tries thumbnail_path then local_path."""
    from pathlib import Path
    from flask import current_app, send_file
    from app.models.listing import ApartmentImage

    img = db.session.get(ApartmentImage, image_id)
    if not img:
        abort(404)
    # Prefer thumbnail
    for p in (img.thumbnail_path, img.local_path):
        if not p:
            continue
        path = Path(p)
        if not path.is_absolute():
            path = Path(current_app.config["IMAGE_DIR"]) / p
        if path.is_file():
            return send_file(str(path))
    abort(404)


@bp.route("/images/<int:image_id>/full")
def image_full(image_id: int):
    """Serve the full-size original (used by the lightbox viewer)."""
    from pathlib import Path
    from flask import current_app, send_file
    from app.models.listing import ApartmentImage

    img = db.session.get(ApartmentImage, image_id)
    if not img:
        abort(404)
    for p in (img.local_path, img.thumbnail_path):
        if not p:
            continue
        path = Path(p)
        if not path.is_absolute():
            path = Path(current_app.config["IMAGE_DIR"]) / p
        if path.is_file():
            return send_file(str(path))
    abort(404)


# -------------------- ratings --------------------

@bp.route("/apartments/<int:apt_id>/rate", methods=["POST"])
def rate(apt_id: int):
    apt = db.session.get(Apartment, apt_id)
    if not apt:
        abort(404)
    g.ctx.check_apartment(apt)
    data = request.get_json(silent=True) or {}
    cat_id = data.get("category_id")
    score = data.get("score")
    comment = data.get("comment")

    if cat_id is None:
        return jsonify({"error": "category_id required"}), 400
    cat = db.session.get(RatingCategory, cat_id)
    if not cat:
        return jsonify({"error": "category not found"}), 404
    # Ensure category is visible in this apartment's context
    visible_ids = {c.id for c in g.ctx.category_query().all()}
    if cat_id not in visible_ids:
        return jsonify({"error": "category not found"}), 404

    if score is None:
        # treat as deletion
        existing = ApartmentRating.query.filter_by(
            apartment_id=apt_id, user_id=current_user.id, category_id=cat_id
        ).first()
        if existing:
            db.session.delete(existing)
            db.session.commit()
        return jsonify({"ok": True, "deleted": True,
                        "personal_score": calculate_score(apt_id, current_user.id),
                        "average_score": calculate_average_score(apt_id)})

    try:
        score_f = float(score)
    except (TypeError, ValueError):
        return jsonify({"error": "score must be a number"}), 400
    score_f = max(cat.min_score, min(cat.max_score, score_f))

    rating = ApartmentRating.query.filter_by(
        apartment_id=apt_id, user_id=current_user.id, category_id=cat_id
    ).first()
    if rating:
        rating.score = score_f
        if comment is not None:
            rating.comment = comment
    else:
        rating = ApartmentRating(
            apartment_id=apt_id,
            user_id=current_user.id,
            category_id=cat_id,
            score=score_f,
            comment=comment,
        )
        db.session.add(rating)
    db.session.commit()
    log_action("apartment_rated", target_type="Apartment", target_id=apt_id,
              details={"category_id": cat_id, "score": score_f})
    return jsonify({
        "ok": True,
        "personal_score": calculate_score(apt_id, current_user.id),
        "average_score": calculate_average_score(apt_id),
    })


# -------------------- statuses --------------------

@bp.route("/apartments/<int:apt_id>/status", methods=["POST"])
def set_status(apt_id: int):
    apt = db.session.get(Apartment, apt_id)
    if not apt:
        abort(404)
    g.ctx.check_apartment(apt)
    data = request.get_json(silent=True) or {}
    status_value = data.get("status")
    if not status_value:
        return jsonify({"error": "status required"}), 400
    try:
        status_enum = StatusEnum(status_value)
    except ValueError:
        return jsonify({"error": "invalid status"}), 400

    row = UserApartmentStatus.query.filter_by(
        user_id=current_user.id, apartment_id=apt_id
    ).first()
    if row:
        row.status = status_enum
    else:
        row = UserApartmentStatus(
            user_id=current_user.id, apartment_id=apt_id, status=status_enum
        )
        db.session.add(row)
    db.session.commit()
    log_action("apartment_status_changed", target_type="Apartment", target_id=apt_id,
               details={"status": status_enum.value})
    return jsonify({"ok": True, "status": status_enum.value})


# -------------------- tags --------------------

@bp.route("/apartments/<int:apt_id>/tags", methods=["POST"])
def add_tag(apt_id: int):
    apt = db.session.get(Apartment, apt_id)
    if not apt:
        abort(404)
    g.ctx.check_apartment(apt)
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    slug = name.lower().replace(" ", "-")
    tag = Tag.query.filter_by(slug=slug).first()
    if not tag:
        tag = Tag(name=name, slug=slug, color=data.get("color") or "#6c757d")
        db.session.add(tag)
        db.session.flush()
    if tag not in apt.tags:
        apt.tags.append(tag)
    db.session.commit()
    log_action("apartment_tag_added", target_type="Apartment", target_id=apt_id,
               details={"tag": tag.name})
    return jsonify({"ok": True, "tag": {"id": tag.id, "name": tag.name, "color": tag.color}})


@bp.route("/apartments/<int:apt_id>/tags/<int:tag_id>", methods=["DELETE"])
def remove_tag(apt_id: int, tag_id: int):
    apt = db.session.get(Apartment, apt_id)
    if not apt:
        abort(404)
    g.ctx.check_apartment(apt)
    tag = db.session.get(Tag, tag_id)
    if not tag:
        abort(404)
    if tag in apt.tags:
        apt.tags.remove(tag)
        db.session.commit()
    return jsonify({"ok": True})


# -------------------- notes --------------------

@bp.route("/apartments/<int:apt_id>/notes", methods=["POST"])
def add_note(apt_id: int):
    apt = db.session.get(Apartment, apt_id)
    if not apt:
        abort(404)
    g.ctx.check_apartment(apt)
    data = request.get_json(silent=True) or {}
    content = (data.get("content") or "").strip()
    if not content:
        return jsonify({"error": "content required"}), 400
    note = UserApartmentNote(user_id=current_user.id, apartment_id=apt_id, content=content)
    db.session.add(note)
    db.session.commit()
    return jsonify({"ok": True, "id": note.id, "content": note.content,
                    "created_at": note.created_at.isoformat()})


@bp.route("/notes/<int:note_id>", methods=["DELETE"])
def delete_note(note_id: int):
    note = db.session.get(UserApartmentNote, note_id)
    if not note:
        abort(404)
    if note.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    db.session.delete(note)
    db.session.commit()
    return jsonify({"ok": True})


# -------------------- refresh status (for auto-reload polling) --------------------

@bp.route("/apartments/<int:apt_id>/refresh-status")
def refresh_status(apt_id: int):
    """Returns whether a refresh job is still running for this apartment."""
    apt = db.session.get(Apartment, apt_id)
    if not apt:
        abort(404)
    g.ctx.check_apartment(apt)
    running = ImportJob.query.filter(
        ImportJob.apartment_id == apt_id,
        ImportJob.status.in_([ImportJobStatus.PENDING, ImportJobStatus.RUNNING]),
    ).first() is not None
    return jsonify({"running": running})


# -------------------- travel time recalculation --------------------

@bp.route("/geocode/search")
def geocode_search():
    """Address autocomplete suggestions (Nominatim-backed)."""
    from app.services.geocoding import search as geo_search

    q = (request.args.get("q") or "").strip()
    if len(q) < 3:
        return jsonify({"results": []})
    results = geo_search(q, limit=6)
    return jsonify({"results": results})


@bp.route("/geocode")
def geocode_one():
    """Resolve a single address to coordinates (synchronous)."""
    from app.services.geocoding import geocode as geocode_fn

    address = (request.args.get("address") or "").strip()
    if not address:
        return jsonify({"error": "missing address"}), 400
    coords = geocode_fn(address)
    if not coords:
        return jsonify({"found": False}), 404
    lat, lng = coords
    return jsonify({"found": True, "lat": lat, "lng": lng})


@bp.route("/apartments/<int:apt_id>/price-history")
def price_history(apt_id: int):
    """Return a price-change timeline for charting."""
    from app.models.listing import ApartmentChange
    apt = db.session.get(Apartment, apt_id)
    if not apt:
        abort(404)
    g.ctx.check_apartment(apt)

    changes = (
        ApartmentChange.query
        .filter_by(apartment_id=apt_id)
        .filter(ApartmentChange.field_name == "price")
        .order_by(ApartmentChange.changed_at)
        .all()
    )

    points = []
    # Seed first point from the oldest change's old_value (= original import price)
    if changes and changes[0].old_value:
        try:
            points.append({
                "date": apt.created_at.isoformat() if apt.created_at else changes[0].changed_at.isoformat(),
                "price": float(changes[0].old_value),
            })
        except (ValueError, TypeError):
            pass
    for c in changes:
        if c.new_value:
            try:
                points.append({"date": c.changed_at.isoformat(), "price": float(c.new_value)})
            except (ValueError, TypeError):
                pass
    return jsonify({"points": points})


@bp.route("/isochrone", methods=["POST"])
def isochrone():
    """Proxy an isochrone request to OpenRouteService (keeps API key server-side)."""
    import requests as _req
    data = request.get_json(silent=True) or {}
    lat = data.get("lat")
    lng = data.get("lng")
    minutes = max(5, min(int(data.get("minutes", 30)), 120))
    mode = data.get("mode", "walking")

    from app.models.settings import AppSetting
    api_key = (AppSetting.get("openrouteservice_api_key") or "").strip()
    if not api_key:
        return jsonify({"error": "No OpenRouteService API key configured. Go to Admin → Settings and add key 'openrouteservice_api_key'."}), 503

    profile_map = {
        "walking": "foot-walking",
        "bicycle": "cycling-regular",
        "car":     "driving-car",
    }
    if mode not in profile_map:
        return jsonify({"error": "Isochrones are not available for transit — OpenRouteService has no public transport profile. Switch the mode to Car, Walking, or Bicycle."}), 422
    profile = profile_map[mode]
    try:
        resp = _req.post(
            f"https://api.openrouteservice.org/v2/isochrones/{profile}",
            headers={"Authorization": api_key, "Content-Type": "application/json"},
            json={"locations": [[lng, lat]], "range": [minutes * 60], "range_type": "time"},
            timeout=10,
        )
        if resp.status_code == 401:
            return jsonify({"error": "ORS API key rejected (401). Check Admin → Settings key 'openrouteservice_api_key'."}), 502
        resp.raise_for_status()
        return jsonify(resp.json())
    except _req.exceptions.Timeout:
        return jsonify({"error": "OpenRouteService request timed out."}), 502
    except Exception as exc:
        return jsonify({"error": f"ORS error: {exc}"}), 502


@bp.route("/rq-status/<path:job_id>")
def rq_job_status(job_id: str):
    """Return status of any RQ job by its job_id string."""
    from app.services.importer.jobs import get_rq_job_status
    status = get_rq_job_status(job_id)
    return jsonify({"job_id": job_id, "status": status})


@bp.route("/apartments/<int:apt_id>/llm-status")
def llm_status(apt_id: int):
    """Return whether an LLM enhance job is currently queued/running for this apartment."""
    apt = db.session.get(Apartment, apt_id)
    if not apt:
        abort(404)
    g.ctx.check_apartment(apt)
    from app.services.importer.jobs import get_rq_job_status
    status = get_rq_job_status(f"llm-enhance-{apt_id}")
    return jsonify({"apt_id": apt_id, "status": status})


@bp.route("/travel-times/<int:apt_id>/recalculate", methods=["POST"])
def recalc_travel(apt_id: int):
    apt = db.session.get(Apartment, apt_id)
    if not apt:
        abort(404)
    g.ctx.check_apartment(apt)
    if apt.lat is None or apt.lng is None:
        return jsonify({"error": "apartment has no coordinates"}), 400
    from app.services.routing import calculate_for_apartment

    targets = g.ctx.target_query().all()
    n = 0
    for t in targets:
        if t.lat is None or t.lng is None:
            continue
        n += calculate_for_apartment(apt, t)
    db.session.commit()
    return jsonify({"ok": True, "calculated": n})
