"""Configuration objects for flat-finder."""
from __future__ import annotations

import json
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv


def _utf8_json_dumps(obj) -> str:
    """JSON serializer that emits real UTF-8 instead of \\uXXXX escapes.

    Required for PostgreSQL clusters created with SQL_ASCII encoding: JSONB
    rejects \\uXXXX escape sequences that don't fit the server encoding, but
    accepts the same characters when sent as raw UTF-8 bytes.
    """
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def _load_env() -> None:
    """Load env file from /etc/flat-finder/flat-finder.env or local .env."""
    candidates = [
        os.environ.get("FLAT_FINDER_ENV_FILE"),
        "/etc/flat-finder/flat-finder.env",
        str(Path(__file__).resolve().parent.parent / ".env"),
    ]
    for path in candidates:
        if path and Path(path).is_file():
            load_dotenv(path, override=False)
            break


_load_env()


def _resolve_secret_key() -> str:
    """Return FLASK_SECRET_KEY from env, or generate an ephemeral one.

    An ephemeral key means every process restart invalidates all existing
    sessions and cookies cannot be verified across gunicorn workers if they
    were started before the env var was set.  We warn loudly so a misconfigured
    production install is obvious.
    """
    key = os.environ.get("FLASK_SECRET_KEY")
    if key:
        return key
    import logging
    logging.getLogger(__name__).warning(
        "FLASK_SECRET_KEY is not set — generating a random per-process key. "
        "Sessions will be invalidated on every restart. "
        "Set FLASK_SECRET_KEY in /etc/flat-finder/flat-finder.env for production."
    )
    return secrets.token_hex(32)


class BaseConfig:
    SECRET_KEY = _resolve_secret_key()

    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "postgresql://flatfinder:flatfinder@localhost:5432/flatfinder"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # Force UTF-8 for psycopg2/PostgreSQL connections (SQLite ignores connect_args).
    if SQLALCHEMY_DATABASE_URI.startswith("postgres"):
        SQLALCHEMY_ENGINE_OPTIONS = {
            "pool_pre_ping": True,
            "connect_args": {"client_encoding": "utf8"},
            # Send real UTF-8 bytes instead of \\uXXXX escapes — JSONB on
            # SQL_ASCII clusters rejects the escape form.
            "json_serializer": _utf8_json_dumps,
        }
    else:
        SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

    APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost")

    DATA_DIR = os.environ.get("DATA_DIR", "/var/lib/flat-finder")
    IMAGE_DIR = os.environ.get("IMAGE_DIR", os.path.join(DATA_DIR, "images"))
    SNAPSHOT_DIR = os.environ.get("SNAPSHOT_DIR", os.path.join(DATA_DIR, "snapshots"))

    MAX_IMPORT_DOWNLOAD_SIZE_MB = int(os.environ.get("MAX_IMPORT_DOWNLOAD_SIZE_MB", "20"))
    MAX_IMAGE_DOWNLOAD_SIZE_MB = int(os.environ.get("MAX_IMAGE_DOWNLOAD_SIZE_MB", "10"))
    IMPORT_HTTP_TIMEOUT = int(os.environ.get("IMPORT_HTTP_TIMEOUT", "15"))

    ROUTING_PROVIDER = os.environ.get("ROUTING_PROVIDER", "mock")
    GEOCODING_PROVIDER = os.environ.get("GEOCODING_PROVIDER", "nominatim")
    OPENROUTESERVICE_API_KEY = os.environ.get("OPENROUTESERVICE_API_KEY", "")
    OSRM_BASE_URL = os.environ.get("OSRM_BASE_URL", "")
    NOMINATIM_USER_AGENT = os.environ.get(
        "NOMINATIM_USER_AGENT", "flat-finder/1.0 (admin@example.com)"
    )
    # User-Agent for fetching listing pages. Many portals (IS24, ImmoWelt, …)
    # return 401/403 to obvious bots.  Override via IMPORT_USER_AGENT in .env.
    IMPORT_USER_AGENT = os.environ.get(
        "IMPORT_USER_AGENT",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36",
    )

    LOGIN_RATE_LIMIT = os.environ.get("LOGIN_RATE_LIMIT", "10 per minute")
    ALLOW_REGISTRATION = os.environ.get("ALLOW_REGISTRATION", "false").lower() == "true"

    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

    DEFAULT_SCORE_DISPLAY = os.environ.get("DEFAULT_SCORE_DISPLAY", "both")

    # Number of trusted reverse-proxy hops (Nginx and/or Cloudflare tunnel).
    # Set to 2 if you have BOTH Nginx and a Cloudflare tunnel in front of Gunicorn.
    PROXY_FIX_HOPS = int(os.environ.get("PROXY_FIX_HOPS", "1"))

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_HTTPONLY = True
    WTF_CSRF_TIME_LIMIT = None  # rely on session lifetime

    PERMANENT_SESSION_LIFETIME = 60 * 60 * 24 * 7  # 7 days
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50 MB upload cap


class DevelopmentConfig(BaseConfig):
    DEBUG = True
    SESSION_COOKIE_SECURE = False


class ProductionConfig(BaseConfig):
    DEBUG = False
    SESSION_COOKIE_SECURE = os.environ.get("APP_BASE_URL", "").startswith("https://")
    REMEMBER_COOKIE_SECURE = SESSION_COOKIE_SECURE


class TestingConfig(BaseConfig):
    TESTING = True
    DEBUG = False
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "TEST_DATABASE_URL", "sqlite:///:memory:"
    )
    # SQLite doesn't accept psycopg2-specific connect_args.
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
    SECRET_KEY = "test-secret"
    LOGIN_RATE_LIMIT = "1000 per minute"
    ROUTING_PROVIDER = "mock"


def get_config():
    env = os.environ.get("FLASK_ENV", "production").lower()
    if env in ("development", "dev"):
        return DevelopmentConfig
    if env in ("testing", "test"):
        return TestingConfig
    return ProductionConfig
