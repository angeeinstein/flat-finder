"""Settings blueprint: per-context target addresses and rating categories."""
from __future__ import annotations

from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.forms.admin import TargetAddressForm
from app.forms.rating import RatingCategoryForm
from app.models.location import TargetAddress
from app.models.rating import RatingCategory
from app.services.audit import log_action
from app.services.scoring import DEFAULT_CATEGORIES


bp = Blueprint("settings", __name__, template_folder="../templates")


# ------------------------------------------------------------------ targets

@bp.route("/targets")
@login_required
def targets():
    owned = g.ctx.owned_target_query().order_by(TargetAddress.name).all()
    return render_template("settings/targets.html", owned=owned)


@bp.route("/targets/new", methods=["GET", "POST"])
@login_required
def target_new():
    form = TargetAddressForm()
    if form.validate_on_submit():
        t = TargetAddress(
            name=form.name.data.strip(),
            address=form.address.data.strip(),
            lat=form.lat.data,
            lng=form.lng.data,
            is_active=form.is_active.data,
            **g.ctx.target_defaults(),
        )
        if t.lat is None or t.lng is None:
            from app.services.geocoding import geocode
            coords = geocode(t.address)
            if coords:
                t.lat, t.lng = coords
            else:
                flash("Could not geocode address. You can enter coordinates manually.", "warning")
        db.session.add(t)
        db.session.commit()
        log_action("target_created", target_type="TargetAddress", target_id=t.id)
        flash("Target address saved.", "success")
        return redirect(url_for("settings.targets"))
    return render_template("settings/target_edit.html", form=form, target=None)


@bp.route("/targets/<int:tid>/edit", methods=["GET", "POST"])
@login_required
def target_edit(tid: int):
    t = db.session.get(TargetAddress, tid)
    if not t:
        abort(404)
    g.ctx.check_target(t)
    form = TargetAddressForm(obj=t)
    if form.validate_on_submit():
        addr_changed = (t.address or "") != form.address.data.strip()
        t.name = form.name.data.strip()
        t.address = form.address.data.strip()
        t.lat = form.lat.data
        t.lng = form.lng.data
        t.is_active = form.is_active.data
        if addr_changed or t.lat is None or t.lng is None:
            from app.services.geocoding import geocode
            coords = geocode(t.address)
            if coords:
                t.lat, t.lng = coords
            else:
                flash("Could not geocode address — coordinates not updated.", "warning")
        db.session.commit()
        log_action("target_updated", target_type="TargetAddress", target_id=t.id)
        flash("Target address updated.", "success")
        return redirect(url_for("settings.targets"))
    return render_template("settings/target_edit.html", form=form, target=t)


@bp.route("/targets/<int:tid>/delete", methods=["POST"])
@login_required
def target_delete(tid: int):
    t = db.session.get(TargetAddress, tid)
    if not t:
        abort(404)
    g.ctx.check_target(t)
    name = t.name
    db.session.delete(t)
    db.session.commit()
    log_action("target_deleted", target_type="TargetAddress", target_id=tid, details={"name": name})
    flash(f'Target "{name}" deleted.', "success")
    return redirect(url_for("settings.targets"))


# ------------------------------------------------------------------ rating categories

@bp.route("/categories")
@login_required
def categories():
    owned = g.ctx.owned_category_query().order_by(
        RatingCategory.display_order, RatingCategory.id
    ).all()
    globals_ = RatingCategory.query.filter(
        RatingCategory.owner_id.is_(None), RatingCategory.team_id.is_(None),
        RatingCategory.is_active.is_(True),
    ).order_by(RatingCategory.display_order, RatingCategory.id).all()
    return render_template("settings/categories.html", owned=owned, globals=globals_)


@bp.route("/categories/new", methods=["GET", "POST"])
@login_required
def category_new():
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
            **g.ctx.category_defaults(),
        )
        db.session.add(cat)
        db.session.commit()
        log_action("category_created", target_type="RatingCategory", target_id=cat.id)
        flash("Category saved.", "success")
        return redirect(url_for("settings.categories"))
    return render_template("settings/category_edit.html", form=form, category=None)


@bp.route("/categories/<int:cat_id>/edit", methods=["GET", "POST"])
@login_required
def category_edit(cat_id: int):
    cat = db.session.get(RatingCategory, cat_id)
    if not cat:
        abort(404)
    g.ctx.check_category(cat)
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
        log_action("category_updated", target_type="RatingCategory", target_id=cat.id)
        flash("Category updated.", "success")
        return redirect(url_for("settings.categories"))
    return render_template("settings/category_edit.html", form=form, category=cat)


@bp.route("/categories/<int:cat_id>/delete", methods=["POST"])
@login_required
def category_delete(cat_id: int):
    cat = db.session.get(RatingCategory, cat_id)
    if not cat:
        abort(404)
    g.ctx.check_category(cat)
    name = cat.name
    db.session.delete(cat)
    db.session.commit()
    log_action("category_deleted", target_type="RatingCategory", target_id=cat_id, details={"name": name})
    flash(f'Category "{name}" deleted.', "success")
    return redirect(url_for("settings.categories"))


@bp.route("/ai", methods=["GET", "POST"])
@login_required
def ai_settings():
    if not current_user.is_admin:
        abort(403)

    from app.models.settings import AppSetting
    from app.services.llm import _DEFAULT_MODEL, _DEFAULT_URL, get_available_models

    if request.method == "POST":
        action = request.form.get("form_action", "model")

        if action == "toggles":
            ai_enabled = "1" if request.form.get("ai_enabled") == "on" else "0"
            ai_summary = "1" if request.form.get("ai_summary_enabled") == "on" else "0"
            AppSetting.set("ai_enabled", ai_enabled,
                           description="Master toggle: enable AI field extraction via Ollama")
            AppSetting.set("ai_summary_enabled", ai_summary,
                           description="Whether AI generates a German listing summary")
            db.session.commit()
            log_action("setting_updated", target_type="AppSetting",
                       details={"ai_enabled": ai_enabled, "ai_summary_enabled": ai_summary})
            flash("AI feature settings updated.", "success")
        else:
            selected = request.form.get("ollama_model", "").strip()
            if selected:
                AppSetting.set(
                    "ollama_model", selected,
                    description="Ollama model used for AI field extraction and summary generation",
                )
                db.session.commit()
                log_action("setting_updated", target_type="AppSetting",
                           details={"key": "ollama_model", "value": selected})
                flash(f"AI model set to {selected}.", "success")

        return redirect(url_for("settings.ai_settings"))

    ollama_url = current_app.config.get("OLLAMA_URL", _DEFAULT_URL)
    current_model = AppSetting.get("ollama_model") or _DEFAULT_MODEL
    available = get_available_models(ollama_url)
    ai_enabled = AppSetting.get("ai_enabled") != "0"
    ai_summary_enabled = AppSetting.get("ai_summary_enabled") != "0"
    return render_template(
        "settings/ai.html",
        current_model=current_model,
        available_models=available,
        ollama_url=ollama_url,
        ollama_reachable=bool(available),
        ai_enabled=ai_enabled,
        ai_summary_enabled=ai_summary_enabled,
    )


@bp.route("/categories/seed-defaults", methods=["POST"])
@login_required
def seed_defaults():
    """Copy global default categories into this context."""
    defaults = RatingCategory.query.filter(
        RatingCategory.owner_id.is_(None), RatingCategory.team_id.is_(None),
    ).order_by(RatingCategory.display_order).all()

    ctx_defaults = g.ctx.category_defaults()
    existing_names = {
        c.name.lower() for c in g.ctx.owned_category_query().all()
    }
    added = 0
    for d in defaults:
        if d.name.lower() in existing_names:
            continue
        cat = RatingCategory(
            name=d.name,
            description=d.description,
            weight=d.weight,
            min_score=d.min_score,
            max_score=d.max_score,
            display_order=d.display_order,
            is_active=d.is_active,
            **ctx_defaults,
        )
        db.session.add(cat)
        added += 1
    db.session.commit()
    flash(f"Added {added} default categor{'y' if added == 1 else 'ies'} to your context.", "success")
    return redirect(url_for("settings.categories"))
