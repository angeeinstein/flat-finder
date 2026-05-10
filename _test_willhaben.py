"""Test Willhaben importer: images (count + download), address, description."""
from __future__ import annotations
import sys, os, re, json, io
sys.path.insert(0, os.path.dirname(__file__))

import requests
from bs4 import BeautifulSoup
from PIL import Image

URLS = sys.argv[1:] or [
    "https://www.willhaben.at/iad/object?adId=1309776591",
    "https://www.willhaben.at/iad/object?adId=1170304235",
    "https://www.willhaben.at/iad/object?adId=962278032",
    "https://www.willhaben.at/iad/object?adId=1539940379",
    "https://www.willhaben.at/iad/object?adId=1527269794",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "de-AT,de;q=0.9,en;q=0.8",
}

from app import create_app
from app.services.importer.willhaben import WillhabenImporter

app = create_app()

def count_raw_images(nd: dict) -> tuple[int, int]:
    """Return (advertImage count, floorPlans count) from raw __NEXT_DATA__."""
    ad = nd.get("props", {}).get("pageProps", {}).get("advertDetails") or {}
    ail = ad.get("advertImageList") or {}
    return len(ail.get("advertImage") or []), len(ail.get("floorPlans") or [])

def get_raw_description(nd: dict) -> dict[str, str]:
    """Extract description sections from attributes."""
    ad = nd.get("props", {}).get("pageProps", {}).get("advertDetails") or {}
    attrs: dict[str, str] = {}
    for r in (ad.get("attributes", {}).get("attribute") or []):
        name = r.get("name", "")
        vals = r.get("values") or []
        if vals and isinstance(vals[0], str):
            attrs[name] = vals[0]
    sections = {}
    if "DESCRIPTION" in attrs:
        sections["DESCRIPTION"] = attrs["DESCRIPTION"]
    for k, v in attrs.items():
        if k.startswith("GENERAL_TEXT_ADVERT/") and v:
            sections[k] = v
    return sections

def get_raw_address(nd: dict) -> dict:
    ad = nd.get("props", {}).get("pageProps", {}).get("advertDetails") or {}
    return ad.get("advertAddressDetails") or {}

with app.app_context():
    imp = WillhabenImporter()

    for url in URLS:
        print(f"\n{'='*72}")
        print(f"URL: {url}")

        resp = requests.get(url, headers=HEADERS, timeout=20, allow_redirects=True)
        print(f"HTTP {resp.status_code}  final: {resp.url}  ({len(resp.text)} bytes)")
        if resp.status_code != 200:
            print("  SKIP")
            continue

        # Parse __NEXT_DATA__
        soup = BeautifulSoup(resp.text, "lxml")
        tag = soup.find("script", id="__NEXT_DATA__")
        nd = {}
        if tag and tag.string:
            try:
                nd = json.loads(tag.string)
            except Exception as e:
                print(f"  __NEXT_DATA__ parse error: {e}")

        # Raw counts from structured data
        raw_photos, raw_plans = count_raw_images(nd)
        print(f"\nRaw advertImageList:  advertImage={raw_photos}  floorPlans={raw_plans}  total={raw_photos+raw_plans}")

        # Run importer
        result = imp.extract(resp.url, resp.text, resp)
        print(f"Importer extracted:   {len(result.image_urls)} image URLs")

        # Check image counts match
        expected = raw_photos + raw_plans
        if len(result.image_urls) == expected:
            print(f"  Image count: OK ({expected})")
        else:
            print(f"  Image count MISMATCH: raw={expected} extracted={len(result.image_urls)}")

        # Download and verify each image
        print(f"\nImage details:")
        ok = fail = 0
        for i, img_url in enumerate(result.image_urls):
            try:
                r = requests.get(img_url, headers=HEADERS, timeout=12)
                if r.status_code != 200:
                    print(f"  [{i+1:2d}] HTTP {r.status_code}  {img_url[-60:]}")
                    fail += 1
                    continue
                img = Image.open(io.BytesIO(r.content))
                img.load()
                w, h = img.size
                mode = img.mode
                short, long_ = min(w, h), max(w, h)
                is_gray = mode in ("L", "1", "LA", "P")
                tag_str = " [FLOOR PLAN?]" if is_gray else ""
                size_warn = ""
                if not is_gray and (short < 200 or long_ < 280):
                    size_warn = " [SMALL]"
                print(f"  [{i+1:2d}] {r.status_code} {mode} {w}x{h} {len(r.content):6d}B{tag_str}{size_warn}")
                ok += 1
            except Exception as e:
                print(f"  [{i+1:2d}] ERROR: {e}")
                fail += 1
        print(f"  => {ok} OK, {fail} failed")

        # Address
        print(f"\nAddress (raw advertAddressDetails):")
        raw_addr = get_raw_address(nd)
        print(f"  {json.dumps(raw_addr, ensure_ascii=False)[:300]}")
        print(f"Address (importer):")
        for k in ("address", "postal_code", "city", "country"):
            v = result.fields.get(k)
            if v is not None:
                print(f"  {k}: {v}")
        lat = result.fields.get("lat")
        lng = result.fields.get("lng")
        if lat and lng:
            print(f"  coordinates: {lat}, {lng}")

        # Description sections
        print(f"\nDescription sections (raw HTML attributes):")
        sections = get_raw_description(nd)
        for name, html in sections.items():
            plain = BeautifulSoup(html, "lxml").get_text(separator="\n", strip=True)
            label = name.split("/", 1)[-1] if "/" in name else name
            print(f"  [{label}] ({len(plain)} chars): {plain[:120].replace(chr(10), ' / ')}")

        print(f"Description (importer, first 300 chars):")
        desc = result.fields.get("description") or ""
        print(f"  {desc[:300].replace(chr(10), ' / ')}")

        # Key fields
        print(f"\nKey fields:")
        for k in ("title", "price", "operating_costs", "deposit", "commission",
                  "rooms", "living_area_m2", "floor", "lease_duration_limited",
                  "lease_duration_text", "has_balcony", "has_terrace", "has_garden",
                  "has_parking", "has_cellar", "contact_name", "contact_info"):
            v = result.fields.get(k)
            if v is not None:
                print(f"  {k:25s} = {repr(v)[:90]}")
