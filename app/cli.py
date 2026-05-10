"""Flask CLI commands."""
from __future__ import annotations

import getpass
import os
import sys
from datetime import datetime, timedelta

import click
from flask import Flask
from flask.cli import with_appcontext

from app.extensions import db


def register_cli(app: Flask) -> None:

    @app.cli.command("create-admin")
    @click.option("--username", prompt=True)
    @click.option("--email", prompt=True)
    @click.option("--password", default=None,
                  help="If omitted, you will be prompted (hidden).")
    @with_appcontext
    def create_admin(username: str, email: str, password: str | None):
        """Create or upgrade an admin account."""
        from app.models.user import User, UserRole

        username = username.strip()
        email = email.strip().lower()
        if not password:
            password = getpass.getpass("Password: ")
            confirm = getpass.getpass("Confirm:  ")
            if password != confirm:
                click.echo("Passwords do not match.", err=True)
                sys.exit(1)
        if len(password) < 8:
            click.echo("Password must be at least 8 characters.", err=True)
            sys.exit(1)

        user = User.query.filter(
            (User.username == username) | (User.email == email)
        ).first()
        if user:
            user.role = UserRole.ADMIN
            user.is_active = True
            user.set_password(password)
            click.echo(f"Updated existing user {user.username} to admin.")
        else:
            user = User(username=username, email=email, role=UserRole.ADMIN, is_active=True)
            user.set_password(password)
            db.session.add(user)
            click.echo(f"Created new admin user {username}.")
        db.session.commit()

    @app.cli.command("seed-demo")
    @with_appcontext
    def seed_demo():
        """Insert sample data for UI testing."""
        from app.models.user import User, UserRole
        from app.models.apartment import Apartment
        from app.models.listing import ListingSource
        from app.models.location import TargetAddress
        from app.models.rating import RatingCategory
        from app.services.scoring import seed_default_categories

        # Admin demo user (only if no admin exists)
        if not User.query.filter_by(role=UserRole.ADMIN).first():
            admin = User(username="admin", email="admin@example.com", role=UserRole.ADMIN, is_active=True)
            admin.set_password("changeme123")
            db.session.add(admin)
            click.echo("Created admin/changeme123 — please change this password.")

        # Default categories
        seed_default_categories(commit=False)

        # Sample target
        if not TargetAddress.query.first():
            db.session.add(TargetAddress(
                name="TU Wien",
                address="Karlsplatz 13, 1040 Wien, Austria",
                lat=48.198489, lng=16.369848,
                is_active=True,
            ))

        # Sample apartments
        admin_user = User.query.filter_by(role=UserRole.ADMIN).first()
        owner_id = admin_user.id if admin_user else None
        if not Apartment.query.first():
            samples = [
                dict(title="Bright 2-room near city center", price=950, operating_costs=120,
                     deposit=2850, address="Mariahilfer Straße 100, 1070 Wien",
                     city="Wien", postal_code="1070", country="Austria",
                     lat=48.197, lng=16.343, living_area_m2=55.0, rooms=2,
                     has_balcony=True, is_furnished=False),
                dict(title="Cozy studio with garden access", price=720, operating_costs=80,
                     deposit=2160, address="Lerchenfelder Str. 50, 1080 Wien",
                     city="Wien", postal_code="1080", country="Austria",
                     lat=48.211, lng=16.346, living_area_m2=32.0, rooms=1,
                     has_garden=True),
                dict(title="Modern 3-room family apartment", price=1500, operating_costs=200,
                     deposit=4500, address="Stadlauer Str. 25, 1220 Wien",
                     city="Wien", postal_code="1220", country="Austria",
                     lat=48.232, lng=16.470, living_area_m2=85.0, rooms=3,
                     has_balcony=True, has_parking=True),
            ]
            for s in samples:
                apt = Apartment(owner_id=owner_id, created_by_id=owner_id, **s)
                db.session.add(apt)
        db.session.commit()
        click.echo("Demo data seeded.")

    @app.cli.command("refresh-listings")
    @with_appcontext
    def refresh_listings():
        """Enqueue refresh jobs for all active listing sources."""
        from app.models.listing import ListingSource
        from app.services.importer.jobs import enqueue_refresh

        count = 0
        for src in ListingSource.query.filter_by(is_active=True).all():
            enqueue_refresh(src.id)
            count += 1
        click.echo(f"Enqueued {count} refresh jobs.")

    @app.cli.command("recalc-travel-times")
    @with_appcontext
    def recalc_travel_times():
        """Recalculate travel times using each apartment's own context targets."""
        from app.models.apartment import Apartment
        from app.models.location import TargetAddress
        from app.services.routing import calculate_for_apartment
        apartments = Apartment.query.filter(Apartment.lat.isnot(None)).all()
        n = 0
        for apt in apartments:
            if apt.team_id is not None:
                targets = TargetAddress.query.filter(
                    TargetAddress.is_active.is_(True),
                    TargetAddress.team_id == apt.team_id,
                ).all()
            elif apt.owner_id is not None:
                targets = TargetAddress.query.filter(
                    TargetAddress.is_active.is_(True),
                    TargetAddress.owner_id == apt.owner_id,
                    TargetAddress.team_id.is_(None),
                ).all()
            else:
                targets = []
            for tgt in targets:
                if tgt.lat is None or tgt.lng is None:
                    continue
                calculate_for_apartment(apt, tgt)
                n += 1
        db.session.commit()
        click.echo(f"Recalculated {n} travel-time entries.")

    @app.cli.command("recalc-scores")
    @with_appcontext
    def recalc_scores():
        """No-op: scores are computed on-demand."""
        click.echo("Scores are computed on the fly; nothing to recalc.")

    @app.cli.command("backfill-targets")
    @with_appcontext
    def backfill_targets():
        """Migrate TargetAddress.user_id → owner_id for existing personal targets."""
        from app.models.location import TargetAddress
        from sqlalchemy import update, text

        # If owner_id column exists and user_id exists, copy user_id → owner_id where needed
        try:
            result = db.session.execute(
                text("""
                    UPDATE target_addresses
                    SET owner_id = user_id
                    WHERE user_id IS NOT NULL AND owner_id IS NULL
                """)
            )
            db.session.commit()
            click.echo(f"Backfilled owner_id for {result.rowcount} target addresses.")
        except Exception as e:
            db.session.rollback()
            click.echo(f"Backfill targets skipped (may not be needed): {e}")

    @app.cli.command("backfill-owner-id")
    @with_appcontext
    def backfill_owner_id():
        """Set owner_id = created_by_id for apartments created before teams feature."""
        from app.models.apartment import Apartment
        from sqlalchemy import update

        result = db.session.execute(
            update(Apartment)
            .where(Apartment.owner_id.is_(None), Apartment.created_by_id.isnot(None))
            .values(owner_id=Apartment.created_by_id)
        )
        db.session.commit()
        click.echo(f"Backfilled owner_id for {result.rowcount} apartments.")

    @app.cli.command("check-config")
    @with_appcontext
    def check_config():
        """Verify environment, DB, Redis, and directories."""
        from sqlalchemy import text
        from redis import Redis
        from pathlib import Path

        ok = True

        click.echo("== Environment ==")
        for key in ("FLASK_SECRET_KEY", "DATABASE_URL", "REDIS_URL", "DATA_DIR"):
            val = app.config.get(key) if key != "FLASK_SECRET_KEY" else app.config.get("SECRET_KEY")
            present = "✓" if val else "✗"
            click.echo(f"  {present} {key}")
            if not val:
                ok = False

        click.echo("== Database ==")
        try:
            db.session.execute(text("SELECT 1"))
            click.echo("  ✓ database connection")
        except Exception as e:
            click.echo(f"  ✗ database: {e}", err=True)
            ok = False

        click.echo("== Redis ==")
        try:
            r = Redis.from_url(app.config["REDIS_URL"])
            r.ping()
            click.echo("  ✓ redis ping")
        except Exception as e:
            click.echo(f"  ✗ redis: {e}", err=True)
            ok = False

        click.echo("== Directories ==")
        for key in ("DATA_DIR", "IMAGE_DIR", "SNAPSHOT_DIR"):
            path = Path(app.config[key])
            if path.is_dir():
                click.echo(f"  ✓ {key}={path}")
            else:
                click.echo(f"  ✗ {key}={path} (does not exist)")
                ok = False

        if ok:
            click.echo("\nAll checks passed.")
        else:
            click.echo("\nSome checks failed.", err=True)
            sys.exit(1)
