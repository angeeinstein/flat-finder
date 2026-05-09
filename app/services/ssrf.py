"""URL validation and SSRF prevention utilities."""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse, urlunparse

import requests
from requests.adapters import HTTPAdapter


class SSRFError(ValueError):
    """Raised when a URL fails SSRF validation."""


def _is_blocked_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True  # treat unknown as blocked
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    )


def _resolve(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError):
        return []
    return list({info[4][0] for info in infos})


def validate_import_url(url: str) -> str:
    """Validate URL for safe outbound fetching.

    Returns the cleaned URL. Raises SSRFError on rejection.
    """
    if not url or len(url) > 2000:
        raise SSRFError("URL is empty or too long.")
    url = url.strip()
    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        raise SSRFError("Only http(s) URLs are allowed.")
    if not parsed.netloc:
        raise SSRFError("URL has no host.")

    host = parsed.hostname or ""
    if not host:
        raise SSRFError("URL has no host.")

    lowered = host.lower()
    if lowered in ("localhost", "ip6-localhost", "ip6-loopback") or lowered.endswith(".localhost"):
        raise SSRFError(f"Host {host!r} is not allowed.")
    if lowered.endswith(".local") or lowered.endswith(".internal"):
        raise SSRFError(f"Host {host!r} is not allowed.")

    # If host is already an IP, check directly
    try:
        ipaddress.ip_address(host)
        ips = [host]
    except ValueError:
        ips = _resolve(host)
        if not ips:
            raise SSRFError(f"Could not resolve {host!r}.")

    for ip in ips:
        if _is_blocked_ip(ip):
            raise SSRFError(f"Host resolves to a blocked address ({ip}).")

    # Reject userinfo (auth in URL)
    if parsed.username or parsed.password:
        raise SSRFError("URLs with credentials are not allowed.")

    # Normalize: drop fragment, keep query
    cleaned = urlunparse(
        (parsed.scheme, parsed.netloc, parsed.path or "/", parsed.params, parsed.query, "")
    )
    return cleaned


def safe_get(url: str, *, timeout: int = 15, max_size_bytes: int = 20 * 1024 * 1024,
             allow_redirects: bool = True, max_redirects: int = 3,
             user_agent: str = "flat-finder/1.0") -> requests.Response:
    """GET a URL safely. Validates URL, limits redirects and download size."""
    url = validate_import_url(url)
    session = requests.Session()
    session.max_redirects = max_redirects

    headers = {
        "User-Agent": user_agent,
        "Accept": "text/html,application/json,application/xhtml+xml;q=0.9,*/*;q=0.5",
        "Accept-Language": "en,de;q=0.8",
    }

    # Re-validate after each redirect
    final_url = url
    for _ in range(max_redirects + 1):
        resp = session.get(final_url, headers=headers, timeout=timeout, stream=True,
                           allow_redirects=False)
        if 300 <= resp.status_code < 400 and allow_redirects:
            loc = resp.headers.get("Location")
            if not loc:
                break
            # Resolve relative to current URL
            from urllib.parse import urljoin
            final_url = validate_import_url(urljoin(final_url, loc))
            continue
        # Read with size cap
        chunks = []
        total = 0
        for chunk in resp.iter_content(chunk_size=64 * 1024):
            if not chunk:
                break
            total += len(chunk)
            if total > max_size_bytes:
                resp.close()
                raise SSRFError(f"Response exceeded max size of {max_size_bytes} bytes.")
            chunks.append(chunk)
        resp._content = b"".join(chunks)  # type: ignore[attr-defined]
        resp._content_consumed = True  # type: ignore[attr-defined]
        return resp
    raise SSRFError("Too many redirects.")
