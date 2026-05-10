"""Analyze structure of an immobilienscout24.at listing.

Run with:  python _analyze_immoscout24.py [url]
"""
from __future__ import annotations
import json, re, sys
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse

URL = (
    sys.argv[1]
    if len(sys.argv) > 1
    else "https://www.immobilienscout24.at/expose/69fd592474ad1b054f4b8814"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "de-AT,de;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

print(f"Fetching {URL} ...")
resp = requests.get(URL, headers=HEADERS, timeout=20, allow_redirects=True)
print(f"HTTP {resp.status_code}  final URL: {resp.url}  ({len(resp.text)} bytes)\n")

html = resp.text
soup = BeautifulSoup(html, "lxml")

# ── 1. Page technology fingerprint ──────────────────────────────────────────
print("=== 1. PAGE TECHNOLOGY ===")
for sid in ("__NEXT_DATA__", "__NUXT_DATA__", "__NUXT__", "__INITIAL_STATE__",
            "__APP_STATE__", "__PRELOADED_STATE__"):
    tag = soup.find("script", id=sid)
    if tag:
        size = len(tag.string or "")
        print(f"  Found script#{sid}  ({size} bytes)")

# Also check for inline state via common variable patterns
for pattern in (r"window\.__INITIAL_STATE__\s*=", r"window\.__STATE__\s*=",
                r"window\.IS24\s*=", r"window\.APP_DATA\s*="):
    scripts_with = [s for s in soup.find_all("script") if re.search(pattern, s.string or "")]
    if scripts_with:
        print(f"  Found inline script matching '{pattern}' ({sum(len(s.string or '') for s in scripts_with)} bytes)")

# ── 2. JSON-LD ───────────────────────────────────────────────────────────────
print("\n=== 2. JSON-LD BLOCKS ===")
ld_blocks = []
for s in soup.find_all("script", type="application/ld+json"):
    if not s.string:
        continue
    try:
        data = json.loads(s.string)
    except Exception:
        print("  [invalid JSON-LD]")
        continue
    entries = data if isinstance(data, list) else [data]
    for e in entries:
        t = e.get("@type", "unknown")
        ld_blocks.append(e)
        keys = list(e.keys())
        print(f"  @type={t}  keys={keys}")
        if "address" in e:
            print(f"    address={json.dumps(e['address'], ensure_ascii=False)}")
        if "geo" in e:
            print(f"    geo={e['geo']}")
        if "offers" in e:
            print(f"    offers={e['offers']}")
        if "image" in e:
            imgs = e["image"]
            if isinstance(imgs, list):
                print(f"    image list: {len(imgs)} items")
                for i in imgs[:3]:
                    print(f"      {i}")
            else:
                print(f"    image: {str(imgs)[:200]}")
        if "numberOfRooms" in e:
            print(f"    numberOfRooms={e['numberOfRooms']}")
        if "floorSize" in e:
            print(f"    floorSize={e['floorSize']}")

# ── 3. OpenGraph / Meta ──────────────────────────────────────────────────────
print("\n=== 3. OG / META TAGS ===")
interesting = ["og:title", "og:description", "og:image", "og:url",
               "og:type", "og:locale", "twitter:title", "twitter:image",
               "description", "keywords"]
for prop in interesting:
    tag = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
    if tag:
        print(f"  {prop}: {(tag.get('content') or '')[:200]}")

# ── 4. Canonical URL ─────────────────────────────────────────────────────────
canon = soup.find("link", rel="canonical")
print(f"\n  canonical: {canon.get('href') if canon else '—'}")

# ── 5. Inline JSON state ─────────────────────────────────────────────────────
print("\n=== 5. INLINE SCRIPT STATE ===")

def try_parse_script(script_tag) -> dict | list | None:
    text = script_tag.string or ""
    # Try the whole thing
    try:
        return json.loads(text)
    except Exception:
        pass
    # Try extracting after '='
    m = re.search(r"=\s*(\{.*)", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1).rstrip(";"))
        except Exception:
            pass
    return None

state_data: dict | list | None = None

# Check known state script IDs
for sid in ("__NEXT_DATA__", "__NUXT_DATA__", "__NUXT__", "__INITIAL_STATE__"):
    tag = soup.find("script", id=sid)
    if tag and tag.string:
        try:
            state_data = json.loads(tag.string)
            print(f"  Parsed script#{sid}  (top-level keys: {list(state_data.keys()) if isinstance(state_data, dict) else type(state_data).__name__})")
            break
        except Exception as e:
            print(f"  script#{sid} parse error: {e}")

# Check large application/json scripts
if state_data is None:
    for s in soup.find_all("script", type="application/json"):
        if len(s.string or "") > 1000:
            try:
                state_data = json.loads(s.string)
                print(f"  Parsed application/json script  (type: {type(state_data).__name__}, len: {len(s.string)})")
                break
            except Exception:
                pass

# Check large untyped inline scripts for embedded JSON
if state_data is None:
    candidates = []
    for s in soup.find_all("script"):
        if s.get("src") or s.get("type") in ("application/ld+json",):
            continue
        text = s.string or ""
        if len(text) > 2000:
            candidates.append((len(text), s))
    candidates.sort(reverse=True)
    for size, s in candidates[:5]:
        parsed = try_parse_script(s)
        if parsed:
            state_data = parsed
            print(f"  Parsed large inline script ({size} bytes, type: {type(parsed).__name__})")
            break

if state_data is None:
    print("  No parseable inline state found.")

# ── 6. Deep-dive into state data ─────────────────────────────────────────────
def walk_keys(node, depth=0, max_depth=6, path=""):
    """Print the key structure of the state tree."""
    if depth > max_depth:
        return
    indent = "  " * depth
    if isinstance(node, dict):
        for k, v in node.items():
            subpath = f"{path}/{k}"
            type_str = type(v).__name__
            if isinstance(v, (dict, list)):
                size = len(v)
                print(f"{indent}{k}: {type_str}[{size}]")
                # Only recurse into non-trivial branches
                if size > 0 and depth < max_depth:
                    walk_keys(v, depth+1, max_depth, subpath)
            elif isinstance(v, str) and len(v) > 100:
                print(f"{indent}{k}: str({len(v)})")
            else:
                print(f"{indent}{k}: {repr(v)[:80]}")
    elif isinstance(node, list) and len(node) > 0:
        print(f"{indent}[list of {len(node)}]  first item type: {type(node[0]).__name__}")
        if isinstance(node[0], dict):
            walk_keys(node[0], depth+1, max_depth, path+"[0]")

if state_data is not None:
    print("\n=== 6. STATE KEY TREE (max depth 5) ===")
    walk_keys(state_data, max_depth=5)

# ── 7. Image URLs ────────────────────────────────────────────────────────────
print("\n=== 7. IMAGE URLS ===")
found_images: list[str] = []

# From JSON-LD
for e in ld_blocks:
    imgs = e.get("image")
    if isinstance(imgs, list):
        for i in imgs:
            if isinstance(i, str):
                found_images.append(i)
            elif isinstance(i, dict):
                found_images.append(i.get("url") or i.get("contentUrl") or "")
    elif isinstance(imgs, str):
        found_images.append(imgs)

# From OG tags
for tag in soup.find_all("meta", attrs={"property": "og:image"}):
    c = tag.get("content", "")
    if c:
        found_images.append(c)

# From state data
IMAGE_EXT_RE = re.compile(r"\.(?:jpe?g|png|webp|avif)(?:\?|#|$)", re.IGNORECASE)
IS24_IMG_RE  = re.compile(r"(?:img|bilder|photos|media|cdn|pictures|immobilien|is24|scout).*\.(jpe?g|png|webp)", re.IGNORECASE)

def collect_image_strings(node, out: list, seen: set, depth=0):
    if depth > 15:
        return
    if isinstance(node, str):
        if (
            node.startswith(("http://", "https://", "//"))
            and (IMAGE_EXT_RE.search(node) or IS24_IMG_RE.search(node))
            and node not in seen
            and len(node) > 20
        ):
            seen.add(node)
            out.append(node)
    elif isinstance(node, dict):
        for v in node.values():
            collect_image_strings(v, out, seen, depth+1)
    elif isinstance(node, list):
        for v in node:
            collect_image_strings(v, out, seen, depth+1)

state_images: list[str] = []
state_seen: set[str] = set()
if state_data is not None:
    collect_image_strings(state_data, state_images, state_seen)

all_images = list(dict.fromkeys(found_images + state_images))
print(f"  Total unique image URLs found: {len(all_images)}")
for i, u in enumerate(all_images[:30]):
    print(f"  [{i+1:2d}] {u}")
if len(all_images) > 30:
    print(f"  ... and {len(all_images)-30} more")

# ── 8. Address / location data ───────────────────────────────────────────────
print("\n=== 8. ADDRESS & LOCATION ===")

# From JSON-LD
for e in ld_blocks:
    addr = e.get("address")
    geo  = e.get("geo")
    if addr:
        print(f"  JSON-LD address: {json.dumps(addr, ensure_ascii=False)}")
    if geo:
        print(f"  JSON-LD geo: {geo}")

# From state data — search for lat/lng and address patterns
def find_address_nodes(node, depth=0):
    if depth > 12:
        return
    if isinstance(node, dict):
        has_lat = any(k.lower() in ("lat", "latitude", "geo_latitude", "geolatitude") for k in node)
        has_lng = any(k.lower() in ("lng", "lon", "longitude", "geo_longitude", "geolongitude") for k in node)
        has_addr = any(k.lower() in ("address", "street", "postcode", "zipcode", "city", "district", "location") for k in node)
        if has_lat and has_lng:
            print(f"  [depth={depth}] Geo node: " + json.dumps({k:v for k,v in node.items() if not isinstance(v, (dict, list))}, ensure_ascii=False)[:400])
        if has_addr and not isinstance(node.get("address") or node.get("street"), (dict, list)):
            print(f"  [depth={depth}] Address node: " + json.dumps({k:v for k,v in node.items() if isinstance(v, (str, int, float))}, ensure_ascii=False)[:400])
        for v in node.values():
            find_address_nodes(v, depth+1)
    elif isinstance(node, list):
        for v in node:
            find_address_nodes(v, depth+1)

if state_data is not None:
    find_address_nodes(state_data)

# ── 9. Key attributes (price, area, rooms) ───────────────────────────────────
print("\n=== 9. KEY ATTRIBUTES ===")

# From JSON-LD
for e in ld_blocks:
    for key in ("name", "numberOfRooms", "floorSize", "offers", "price"):
        if key in e:
            print(f"  JSON-LD {key}: {e[key]}")

# From state — look for price/area/rooms-ish keys
def find_attr_nodes(node, depth=0):
    if depth > 10:
        return
    price_keys = {"price", "mietpreis", "kaufpreis", "gesamtmiete", "betriebskosten",
                  "warmmiete", "kaltmiete", "monatsmiete", "rent", "costs", "totalrent"}
    area_keys  = {"wohnflaeche", "flaeche", "nutzflaeche", "livingarea", "area", "m2",
                  "livingspace", "size"}
    room_keys  = {"zimmer", "rooms", "numberofrooms", "roomcount", "anzahlzimmer"}
    if isinstance(node, dict):
        lc_keys = {k.lower().replace("_","").replace("-",""): k for k in node}
        for lck, origk in lc_keys.items():
            v = node[origk]
            if lck in price_keys and isinstance(v, (int, float, str)):
                print(f"  [depth={depth}] PRICE key={origk} val={v!r}")
            if lck in area_keys and isinstance(v, (int, float, str)):
                print(f"  [depth={depth}] AREA  key={origk} val={v!r}")
            if lck in room_keys and isinstance(v, (int, float, str)):
                print(f"  [depth={depth}] ROOMS key={origk} val={v!r}")
        for v in node.values():
            find_attr_nodes(v, depth+1)
    elif isinstance(node, list):
        for v in node:
            find_attr_nodes(v, depth+1)

if state_data is not None:
    find_attr_nodes(state_data)

# Regex from page text as last resort
text = soup.get_text(" ", strip=True)
for label, pattern in [
    ("Price",  r"([\d.,]+)\s*(?:€|EUR)"),
    ("Area",   r"([\d.,]+)\s*m²"),
    ("Rooms",  r"([\d.,]+)\s*(?:Zimmer|Räume)"),
]:
    m = re.search(pattern, text)
    if m:
        window = text[max(0,m.start()-50):m.end()+50]
        print(f"  Regex {label}: '{m.group()}'  context: ...{window}...")

# ── 10. Title & Description ──────────────────────────────────────────────────
print("\n=== 10. TITLE & DESCRIPTION ===")
og_title = soup.find("meta", property="og:title")
og_desc  = soup.find("meta", property="og:description")
page_title = soup.find("title")
print(f"  <title>:        {(page_title.string or '').strip()[:200] if page_title else '—'}")
print(f"  og:title:       {(og_title.get('content','') if og_title else '—')[:200]}")
print(f"  og:description: {(og_desc.get('content','') if og_desc else '—')[:400]}")

# From JSON-LD
for e in ld_blocks:
    if "name" in e or "description" in e:
        print(f"  JSON-LD name:  {str(e.get('name',''))[:200]}")
        print(f"  JSON-LD desc:  {str(e.get('description',''))[:400]}")

# ── 11. Save raw state data for manual inspection ─────────────────────────────
if state_data is not None:
    out_file = "_immoscout24_state.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(state_data, f, ensure_ascii=False, indent=2)
    print(f"\n=== STATE DATA saved to {out_file} ===")
else:
    out_file = "_immoscout24_page.html"
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n=== No state data found — raw HTML saved to {out_file} ===")

print("\nDone.")
