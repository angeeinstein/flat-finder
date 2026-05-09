"""Auth blueprint: login, logout, first-admin setup."""
from datetime import datetime
from urllib.parse import urlparse

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from app.extensions import db, limiter
from app.forms.auth import FirstAdminForm, LoginForm
from app.models.user import User, UserRole
from app.services.audit import log_action


bp = Blueprint("auth", __name__, template_folder="../templates")


def _is_safe_url(target: str) -> bool:
    if not target:
        return False
    ref = urlparse(request.host_url)
    test = urlparse(target if target.startswith("/") else target)
    if test.netloc and test.netloc != ref.netloc:
        return False
    return target.startswith("/") and not target.startswith("//")


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit(lambda: current_app.config.get("LOGIN_RATE_LIMIT", "10 per minute"))
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    # If no admin exists, force first-admin setup
    admin_exists = db.session.query(User.id).filter(User.role == UserRole.ADMIN).first()
    if not admin_exists:
        return redirect(url_for("auth.first_admin"))

    form = LoginForm()
    if form.validate_on_submit():
        identifier = form.username.data.strip()
        user = User.query.filter(
            (User.username == identifier) | (User.email == identifier.lower())
        ).first()
        if user and user.is_active and user.check_password(form.password.data):
            login_user(user, remember=form.remember.data)
            user.last_login_at = datetime.utcnow()
            db.session.commit()
            log_action("login", user_id=user.id)
            next_url = request.args.get("next") or request.form.get("next")
            if next_url and _is_safe_url(next_url):
                return redirect(next_url)
            return redirect(url_for("main.dashboard"))
        flash("Invalid username/email or password.", "danger")
    return render_template("auth/login.html", form=form)


@bp.route("/logout")
@login_required
def logout():
    log_action("logout", user_id=current_user.id)
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))


@bp.route("/first-admin", methods=["GET", "POST"])
def first_admin():
    admin_exists = db.session.query(User.id).filter(User.role == UserRole.ADMIN).first()
    if admin_exists:
        return redirect(url_for("auth.login"))

    form = FirstAdminForm()
    if form.validate_on_submit():
        existing = User.query.filter(
            (User.username == form.username.data)
            | (User.email == form.email.data.lower())
        ).first()
        if existing:
            flash("A user with that username or email already exists.", "danger")
        else:
            user = User(
                username=form.username.data.strip(),
                email=form.email.data.strip().lower(),
                role=UserRole.ADMIN,
                is_active=True,
            )
            user.set_password(form.password.data)
            db.session.add(user)
            db.session.commit()
            login_user(user)
            log_action("first_admin_created", user_id=user.id, target_type="User", target_id=user.id)
            flash("Admin account created. Welcome!", "success")
            return redirect(url_for("main.dashboard"))
    return render_template("auth/first_admin.html", form=form)
