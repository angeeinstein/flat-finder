"""SSRF prevention tests."""
import pytest

from app.services.ssrf import SSRFError, validate_import_url


def test_valid_https_url(app):
    with app.app_context():
        result = validate_import_url("https://www.willhaben.at/iad/immobilien/foo/123")
        assert result.startswith("https://")


def test_rejects_localhost(app):
    with app.app_context():
        with pytest.raises(SSRFError):
            validate_import_url("http://localhost/")


def test_rejects_127_loopback(app):
    with app.app_context():
        with pytest.raises(SSRFError):
            validate_import_url("http://127.0.0.1/")


def test_rejects_private_ip(app):
    with app.app_context():
        with pytest.raises(SSRFError):
            validate_import_url("http://192.168.1.1/")
        with pytest.raises(SSRFError):
            validate_import_url("http://10.0.0.5/")
        with pytest.raises(SSRFError):
            validate_import_url("http://172.16.0.1/")


def test_rejects_link_local(app):
    with app.app_context():
        with pytest.raises(SSRFError):
            validate_import_url("http://169.254.169.254/")


def test_rejects_non_http_scheme(app):
    with app.app_context():
        with pytest.raises(SSRFError):
            validate_import_url("file:///etc/passwd")
        with pytest.raises(SSRFError):
            validate_import_url("gopher://example.com/")


def test_rejects_userinfo(app):
    with app.app_context():
        with pytest.raises(SSRFError):
            validate_import_url("http://user:pass@example.com/")


def test_rejects_dot_internal(app):
    with app.app_context():
        with pytest.raises(SSRFError):
            validate_import_url("http://server.internal/path")
