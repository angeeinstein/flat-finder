"""pytest fixtures for flat-finder."""
from __future__ import annotations

import os
import tempfile

import pytest

os.environ.setdefault("FLASK_ENV", "testing")

from app import create_app  # noqa: E402
from app.config import TestingConfig  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models.user import User, UserRole  # noqa: E402


@pytest.fixture(scope="session")
def app():
    """Create the Flask app once per test session.

    The app context is *not* held open here — that would let Flask-Login's
    g-cached current_user leak between test clients. Tests that need an
    app context should use the `db_session` fixture (or push their own).
    """
    tmpdir = tempfile.mkdtemp(prefix="flat-finder-tests-")

    class Cfg(TestingConfig):
        DATA_DIR = tmpdir
        IMAGE_DIR = os.path.join(tmpdir, "images")
        SNAPSHOT_DIR = os.path.join(tmpdir, "snapshots")
        SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"

    app = create_app(Cfg)
    with app.app_context():
        db.create_all()
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    """Yield a fresh test client per test (own cookie jar). No outer app_context."""
    with app.test_client() as c:
        yield c


@pytest.fixture()
def runner(app):
    return app.test_cli_runner()


@pytest.fixture()
def db_session(app):
    """Push an app context for direct DB access, then pop it after the test."""
    with app.app_context():
        yield db.session
        db.session.rollback()


@pytest.fixture()
def admin_user(app):
    with app.app_context():
        u = User.query.filter_by(username="admin").first()
        if not u:
            u = User(username="admin", email="admin@example.com",
                     role=UserRole.ADMIN, is_active=True)
            u.set_password("adminpass1")
            db.session.add(u)
            db.session.commit()
        # detach so the test can still reference attrs
        db.session.expunge(u)
        return u


@pytest.fixture()
def regular_user(app):
    with app.app_context():
        u = User.query.filter_by(username="alice").first()
        if not u:
            u = User(username="alice", email="alice@example.com",
                     role=UserRole.USER, is_active=True)
            u.set_password("alicepass1")
            db.session.add(u)
            db.session.commit()
        db.session.expunge(u)
        return u


@pytest.fixture()
def login(client):
    """Helper to log in a user via the test client."""
    def _login(username: str, password: str):
        return client.post("/auth/login", data={
            "username": username,
            "password": password,
        }, follow_redirects=False)
    return _login
