"""Authentication and access control tests."""
from app.extensions import db
from app.models.user import User, UserRole


def test_anonymous_redirected_to_first_admin_when_no_admin(client, app):
    with app.app_context():
        User.query.delete()
        db.session.commit()
    resp = client.get("/", follow_redirects=False)
    # Either redirect to first-admin, or to login if an admin already exists
    assert resp.status_code in (302, 303)
    location = resp.headers.get("Location", "")
    assert "/auth/" in location


def test_login_required_for_dashboard(client, admin_user):
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code in (302, 303)
    assert "/auth/login" in resp.headers["Location"]


def test_admin_login_succeeds(client, admin_user, login):
    resp = login("admin", "adminpass1")
    assert resp.status_code == 302
    # Now dashboard accessible
    resp = client.get("/")
    assert resp.status_code == 200


def test_wrong_password_rejected(client, admin_user, login):
    resp = login("admin", "wrongpass")
    assert resp.status_code == 200
    assert b"Invalid" in resp.data


def test_admin_required_blocks_regular_user(client, regular_user, login):
    login("alice", "alicepass1")
    resp = client.get("/admin/", follow_redirects=False)
    assert resp.status_code == 403


def test_admin_can_access_admin(client, admin_user, login):
    login("admin", "adminpass1")
    resp = client.get("/admin/")
    assert resp.status_code == 200
