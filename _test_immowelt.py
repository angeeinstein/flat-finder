"""Test Immowelt importer: images (count + download), address, price, description."""
from __future__ import annotations
import sys, os, re, json, io, html as html_mod
sys.path.insert(0, os.path.dirname(__file__))

import requests
from bs4 import BeautifulSoup
from PIL import Image

URLS = sys.argv[1:] or [
    "https://www.immowelt.at/expose/96a3f8c3-61d2-4e8e-86a4-bb408be9e255",
    "https://www.immowelt.at/expose/ba292d5f-678e-4d9b-83af-10c478d94da1",
    "https://www.immowelt.at/expose/700e585e-38fa-4de2-ad9f-8e621463efdb",
    "https://www.immowelt.at/expose/98a00532-f87a-4765-b0b3-c93d4b9a8158",
    "https://www.immowelt.at/expose/a4bf528e-69be-4ca4-b01a-8c4a2970991c",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "de-AT,de;q=0.9,en;q=0.8",
}

from app import create_app
from app.services.importer.immowelt import ImmoweltImporter

app = create_app()


def parse_lifecycle(html):
    soup = BeautifulSoup(html, "lxml")
    for s in soup.find_all("script"):
        text = (s.string or "").strip()
        if "__UFRN_LIFECYCLE_SERVERREQUEST__" not in text:
            continue
        m = re.match(
            r'window\["__UFRN_LIFECYCLE_SERVERREQUEST__"\]=JSON\.parse\((.+)\);\s*$', text
        )
        if m:
            try:
                return json.loads(json.loads(m.group(1)))
            except Exception:
                pass
    return None


def count_raw_images(data):
    classified = data["app_cldp"]["data"]["classified"]
    gallery = len((classified.get("sections") or {}).get("gallery", {}).get("images") or [])
    fps = len(((classified.get("domains") or {}).get("medias") or {}).get("floorplans") or [])
    return gallery, fps


with app.app_context():
    imp = ImmoweltImporter()

    for url in URLS:
        print(f"\n{'='*72}")
        print(f"URL: {url}")

        resp = requests.get(url, headers=HEADERS, timeout=20, allow_redirects=True)
        print(f"HTTP {resp.status_code}  final: {resp.url}  ({len(resp.text)} bytes)")
        if resp.status_code != 200:
            print("  SKIP")
            continue

        data = parse_lifecycle(resp.text)
        if not data:
            print("  ERROR: could not parse __UFRN_LIFECYCLE_SERVERREQUEST__")
            continue

        raw_gallery, raw_fps = count_raw_images(data)
        expected = raw_gallery + raw_fps
        print(f"\nRaw images: gallery={raw_gallery}  floorplans={raw_fps}  total={expected}")

        result = imp.extract(resp.url, resp.text, resp)
        print(f"Importer extracted: {len(result.image_urls)} image URLs")

        if len(result.image_urls) == expected:
            print(f"  Image count: OK ({expected})")
        else:
            print(f"  Image count MISMATCH: raw={expected} extracted={len(result.image_urls)}")

        # Download + verify images
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
                short, long_ = min(w, h), max(w, h)
                is_gray = img.mode in ("L", "1", "LA", "P")
                tag = " [FP?]" if is_gray else ""
                size_warn = " [SMALL]" if not is_gray and (short < 200 or long_ < 280) else ""
                print(f"  [{i+1:2d}] {r.status_code} {img.mode} {w}x{h}{tag}{size_warn}")
                ok += 1
            except Exception as e:
                print(f"  [{i+1:2d}] ERROR: {e}")
                fail += 1
        print(f"  => {ok} OK, {fail} failed")

        # Address
        classified = data["app_cldp"]["data"]["classified"]
        loc = (classified.get("sections") or {}).get("location") or {}
        raw_addr = loc.get("address") or {}
        print(f"\nAddress (raw): {json.dumps(raw_addr, ensure_ascii=False)}  published={loc.get('isAddressPublished')}")
        print(f"Address (importer):")
        for k in ("address", "postal_code", "city", "country", "address_is_approximate"):
            v = result.fields.get(k)
            if v is not None:
                print(f"  {k}: {v}")
        lat = result.fields.get("lat")
        lng = result.fields.get("lng")
        if lat and lng:
            print(f"  coordinates: {lat}, {lng}")

        # Price
        print(f"\nPrice (importer):")
        for k in ("price", "operating_costs", "total_monthly_cost", "deposit", "commission"):
            v = result.fields.get(k)
            if v is not None:
                print(f"  {k}: {v}")

        # Description
        desc = result.fields.get("description") or ""
        print(f"\nDescription (first 400 chars, {len(desc)} total):")
        print(f"  {desc[:400].replace(chr(10), ' / ')}")

        # Key fields
        print(f"\nKey fields:")
        for k in ("title", "rooms", "living_area_m2", "floor", "floor",
                  "has_balcony", "has_terrace", "has_garden", "has_cellar", "has_parking",
                  "heating_type", "energy_cert_info",
                  "contact_name", "contact_info",
                  "platform", "external_id"):
            v = result.fields.get(k) if k != "title" else result.fields.get("title")
            # title is on result directly for some importers
            if k == "title":
                v = result.fields.get("title")
            if v is not None:
                print(f"  {k:25s} = {repr(v)[:90]}")
        print(f"  {'platform':25s} = {result.platform!r}")
        print(f"  {'external_id':25s} = {result.external_id!r}")
