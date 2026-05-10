"""Test the ImmoScout24 importer — fetches live and runs extraction."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import requests as _requests
from app import create_app
from app.services.importer.immoscout24 import ImmoScout24Importer

URLS = sys.argv[1:] or [
    "https://www.immobilienscout24.at/expose/69fd592474ad1b054f4b8814",
    "https://www.immobilienscout24.at/expose/69f90df0897bd2a11f632792",
    "https://www.immobilienscout24.at/expose/69f07f054631ea0b033ac1fa",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "de-AT,de;q=0.9,en;q=0.8",
}

app = create_app()
with app.app_context():
    imp = ImmoScout24Importer()

    for url in URLS:
        print(f"\n{'='*70}")
        print(f"URL: {url}")
        resp = _requests.get(url, headers=HEADERS, timeout=20)
        print(f"HTTP {resp.status_code}  ({len(resp.text)} bytes)")
        if resp.status_code != 200:
            print("  SKIP — non-200 response")
            continue

        result = imp.extract(url, resp.text, resp)

        print(f"platform:      {result.platform}")
        print(f"external_id:   {result.external_id}")
        print(f"canonical_url: {result.canonical_url}")
        print(f"images:        {len(result.image_urls)}")
        for i, u in enumerate(result.image_urls):
            print(f"  [{i+1:2d}] {u[:110]}")

        print("fields:")
        for k, v in sorted(result.fields.items()):
            if v is not None:
                print(f"  {k:30s} = {repr(v)[:110]}")

        desc = result.fields.get("description") or ""
        print(f"description:   {desc[:200].replace(chr(10), ' ')}")
