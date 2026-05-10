"""Application factory for flat-finder."""
from __future__ import annotations

import logging
import os
from pathlib import Path

from flask import Flask, g, redirect, request, url_for
from flask_login import current_user
from werkzeug.middleware.proxy_fix import ProxyFix

from app.config import get_config
from app.extensions import csrf, db, limiter, login_manager, migrate


def create_app(config_object: object | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=False)

    if config_object is None:
        config_object = get_config()
    app.config.from_object(config_object)

    # Trust proxy headers (Cloudflare tunnel / Nginx). One reverse-proxy hop.
    proxy_hops = int(app.config.get("PROXY_FIX_HOPS", 1))
    app.wsgi_app = ProxyFix(
        app.wsgi_app, x_for=proxy_hops, x_proto=proxy_hops,
        x_host=proxy_hops, x_port=proxy_hops, x_prefix=proxy_hops,
    )

    _configure_logging(app)
    _ensure_data_dirs(app)
    _init_extensions(app)
    _register_blueprints(app)
    _register_cli(app)
    _register_template_globals(app)
    _register_global_login_required(app)

    return app


def _configure_logging(app: Flask) -> None:
    level = getattr(logging, app.config.get("LOG_LEVEL", "INFO").upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    app.logger.setLevel(level)


def _ensure_data_dirs(app: Flask) -> None:
    for key in ("DATA_DIR", "IMAGE_DIR", "SNAPSHOT_DIR"):
        path = app.config.get(key)
        if path:
            try:
                Path(path).mkdir(parents=True, exist_ok=True)
            except OSError:
                app.logger.warning("Could not create directory %s=%s", key, path)


def _init_extensions(app: Flask) -> None:
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)

    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please log in to access this page."
    login_manager.login_message_category = "info"

    from app.models.user import User  # local import to avoid circular

    @login_manager.user_loader
    def load_user(user_id: str):
        try:
            return db.session.get(User, int(user_id))
        except (ValueError, TypeError):
            return None


def _register_blueprints(app: Flask) -> None:
    from app.views.auth import bp as auth_bp
    from app.views.main import bp as main_bp
    from app.views.apartments import bp as apartments_bp
    from app.views.map import bp as map_bp
    from app.views.admin import bp as admin_bp
    from app.views.api import bp as api_bp
    from app.views.teams import bp as teams_bp
    from app.views.settings import bp as settings_bp

    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(main_bp)
    app.register_blueprint(apartments_bp, url_prefix="/apartments")
    app.register_blueprint(map_bp, url_prefix="/map")
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(api_bp, url_prefix="/api")
    app.register_blueprint(teams_bp, url_prefix="/teams")
    app.register_blueprint(settings_bp, url_prefix="/settings")

    csrf.exempt(api_bp)  # API uses its own CSRF token in headers; simpler to exempt


def _register_cli(app: Flask) -> None:
    from app.cli import register_cli

    register_cli(app)


def _register_template_globals(app: Flask) -> None:
    from app.models.user import User

    # Compute a version string from the static CSS file mtime so browsers
    # always pick up the latest styles after a deploy.
    css_path = Path(app.static_folder or "app/static") / "css" / "app.css"
    try:
        static_version = str(int(css_path.stat().st_mtime))
    except OSError:
        static_version = "0"

    @app.context_processor
    def inject_globals():
        ctx = getattr(g, "ctx", None)
        user_teams: list = []
        if current_user.is_authenticated:
            from app.models.team import TeamMember
            memberships = TeamMember.query.filter_by(
                user_id=current_user.id
            ).all()
            user_teams = [m.team for m in memberships if m.team]
        return {
            "app_name": "flat-finder",
            "any_admin_exists": _any_admin_exists,
            "static_version": static_version,
            "active_ctx": ctx,
            "user_teams": user_teams,
        }

    def _any_admin_exists() -> bool:
        from app.models.user import User as _User, UserRole

        return db.session.query(_User.id).filter(
            _User.role == UserRole.ADMIN, _User.is_active.is_(True)
        ).first() is not None


def _register_global_login_required(app: Flask) -> None:
    """Block all anonymous access except for whitelisted endpoints."""
    PUBLIC_ENDPOINTS = {
        "auth.login",
        "auth.logout",
        "auth.first_admin",
        "static",
        "teams.join",  # invite link must be accessible before login redirect
    }

    @app.before_request
    def _require_login():
        endpoint = request.endpoint or ""
        if endpoint in PUBLIC_ENDPOINTS:
            return None
        if endpoint.startswith("static"):
            return None
        if current_user.is_authenticated:
            # Build AppContext and attach to g for this request
            from app.services.context import AppContext
            g.ctx = AppContext.from_session(current_user.id)
            return None
        # Allow first-admin setup if no admin exists yet
        from app.models.user import User as _User, UserRole

        admin_exists = db.session.query(_User.id).filter(
            _User.role == UserRole.ADMIN
        ).first() is not None
        if not admin_exists:
            return redirect(url_for("auth.first_admin"))
        return redirect(url_for("auth.login", next=request.path))
