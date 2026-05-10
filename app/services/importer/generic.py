"""Generic fallback importer using BeautifulSoup, JSON-LD, OpenGraph and meta tags."""
from __future__ import annotations

import json
import re
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from app.services.importer.base import ImporterBase, ImporterResult


PRICE_RE = re.compile(r"(?P<num>[\d.,]+)\s*(?:€|EUR)", re.IGNORECASE)
AREA_RE = re.compile(r"(?P<num>\d{1,4}(?:[.,]\d+)?)\s*m²", re.IGNORECASE)
ROOMS_RE = re.compile(r"(?P<num>\d{1,2}(?:[.,]\d+)?)\s*(?:Zimmer|rooms?)", re.IGNORECASE)


# URL fragments that almost certainly indicate non-property assets
LOGO_HINT_RE = re.compile(
    r"(?:^|[/_\-\.])("
    r"logo|logos|icon|icons|sprite|favicon|avatar|avatars|"
    r"advertisement|advert(?!s?/)|banner|tracking|pixel|placeholder|"
    r"spinner|loader|loading|emoji|button|btn[-_]|badge|"
    r"share|social|fb-|twitter-|instagram-|pinterest-"
    r")(?:[/_\-\.]|$)",
    re.IGNORECASE,
)
SKIP_EXT_RE = re.compile(r"\.(?:svg|ico|gif)(?:\?|#|$)", re.IGNORECASE)
IMAGE_EXT_RE = re.compile(r"\.(?:jpe?g|png|webp|avif)(?:\?|#|$)", re.IGNORECASE)
# Heuristic: image URLs often contain dimension hints like "300x200" or "_400_"
SMALL_DIM_RE = re.compile(r"(?:^|[/_\-])(?:[1-9]?\d|1\d\d)x(?:[1-9]?\d|1\d\d)(?:[/_\-\.]|$)")


def _to_float(s: str) -> float | None:
    if s is None:
        return None
    s = s.strip().replace(" ", "")
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _meta(soup: BeautifulSoup, prop: str) -> str | None:
    tag = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
    if tag and tag.get("content"):
        return (tag.get("content") or "").strip() or None
    return None


def _meta_all(soup: BeautifulSoup, prop: str) -> list[str]:
    out: list[str] = []
    for tag in soup.find_all("meta", attrs={"property": prop}):
        c = (tag.get("content") or "").strip()
        if c:
            out.append(c)
    for tag in soup.find_all("meta", attrs={"name": prop}):
        c = (tag.get("content") or "").strip()
        if c:
            out.append(c)
    return out


def _jsonld(soup: BeautifulSoup) -> list[dict]:
    out: list[dict] = []
    for s in soup.find_all("script", type="application/ld+json"):
        if not s.string:
            continue
        try:
            data = json.loads(s.string)
        except (ValueError, TypeError):
            continue
        if isinstance(data, list):
            out.extend(d for d in data if isinstance(d, dict))
        elif isinstance(data, dict):
            out.append(data)
            graph = data.get("@graph")
            if isinstance(graph, list):
                out.extend(g for g in graph if isinstance(g, dict))
    return out


def _looks_like_property_image(url: str) -> bool:
    """Heuristic filter for image URLs we want to keep."""
    if not url or url.startswith("data:") or url.startswith("blob:"):
        return False
    if SKIP_EXT_RE.search(url):
        return False
    # Allow common image extensions OR no extension (CDNs sometimes drop it)
    if not IMAGE_EXT_RE.search(url) and not re.search(r"/image[s]?/|/photo[s]?/|/media/", url, re.IGNORECASE):
        # If URL has no clear image extension and no image-y path, skip
        # unless it has typical image CDN segments
        if not re.search(r"(?:cache|cdn|images|img|media|bilder|fotos|pic|asset)", url, re.IGNORECASE):
            return False
    if LOGO_HINT_RE.search(url):
        return False
    if SMALL_DIM_RE.search(url):
        return False
    return True


def _walk_for_image_urls(node: Any, out: list[str], seen: set[str], limit: int = 100) -> None:
    """Recursively walk a JSON structure collecting image-like URLs."""
    if len(out) >= limit:
        return
    if isinstance(node, str):
        if (
            node.startswith(("http://", "https://", "//"))
            and IMAGE_EXT_RE.search(node)
            and node not in seen
            and _looks_like_property_image(node)
        ):
            seen.add(node)
            out.append(node if not node.startswith("//") else "https:" + node)
    elif isinstance(node, dict):
        # Prefer keys that hint at images
        for k in ("referenceImageUrl", "mainImageUrl", "url", "contentUrl", "src", "href"):
            v = node.get(k)
            if isinstance(v, str):
                _walk_for_image_urls(v, out, seen, limit)
        for v in node.values():
            _walk_for_image_urls(v, out, seen, limit)
    elif isinstance(node, list):
        for v in node:
            _walk_for_image_urls(v, out, seen, limit)


def _normalize_jsonld_image(value: Any) -> Iterable[str]:
    """Return image URLs from a JSON-LD `image` field (string, list, or dict)."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for v in value:
            yield from _normalize_jsonld_image(v)
    elif isinstance(value, dict):
        for k in ("url", "contentUrl", "@id"):
            v = value.get(k)
            if isinstance(v, str):
                yield v


def _build_address(parts: dict) -> str | None:
    """Compose a human-readable address line from whatever components we have."""
    street = (parts.get("street") or "").strip()
    postal = (parts.get("postal") or "").strip()
    city = (parts.get("city") or "").strip()
    region = (parts.get("region") or "").strip()
    line1 = street
    line2_bits = [p for p in (postal, city) if p]
    line2 = " ".join(line2_bits)
    pieces = [p for p in (line1, line2, region) if p]
    out = ", ".join(pieces)
    return out[:500] or None


class GenericImporter(ImporterBase):
    name = "generic"

    def can_handle(self, url: str) -> bool:
        return True

    def extract(self, url: str, html: str, response) -> ImporterResult:
        soup = BeautifulSoup(html, "lxml")
        result = ImporterResult(platform=urlparse(url).netloc)

        # ----- Title -----
        title = _meta(soup, "og:title")
        if not title and soup.title and soup.title.string:
            title = soup.title.string.strip()
        if title:
            result.fields["title"] = title[:500]

        # ----- Description -----
        desc = _meta(soup, "og:description") or _meta(soup, "description")
        if desc:
            result.fields["description"] = desc

        # ----- Address parts (collected, then composed) -----
        addr_parts: dict = {}

        # ----- JSON-LD -----
        ld_data = _jsonld(soup)
        seen_images: set[str] = set()
        for entry in ld_data:
            t = entry.get("@type")
            types = t if isinstance(t, list) else [t]
            relevant = any(
                x in (
                    "Apartment", "Residence", "Place", "Product", "Offer",
                    "RealEstateListing", "House", "SingleFamilyResidence",
                    "Accommodation",
                )
                for x in types if x
            )
            if not relevant:
                continue

            # Address
            addr = entry.get("address")
            if isinstance(addr, dict):
                if addr.get("streetAddress"):
                    addr_parts.setdefault("street", str(addr["streetAddress"]))
                if addr.get("postalCode"):
                    addr_parts.setdefault("postal", str(addr["postalCode"]))
                if addr.get("addressLocality"):
                    addr_parts.setdefault("city", str(addr["addressLocality"]))
                if addr.get("addressRegion"):
                    addr_parts.setdefault("region", str(addr["addressRegion"]))
                if addr.get("addressCountry"):
                    country = addr["addressCountry"]
                    if isinstance(country, dict):
                        country = country.get("name") or country.get("alternateName")
                    if country:
                        result.fields.setdefault("country", str(country))

            # Geo
            geo = entry.get("geo")
            if isinstance(geo, dict):
                if geo.get("latitude"):
                    result.fields.setdefault("lat", _to_float(str(geo["latitude"])))
                if geo.get("longitude"):
                    result.fields.setdefault("lng", _to_float(str(geo["longitude"])))

            # Floor area
            fa = entry.get("floorSize") or entry.get("area")
            if isinstance(fa, dict):
                val = fa.get("value")
                if val is not None:
                    result.fields.setdefault("living_area_m2", _to_float(str(val)))
            elif fa is not None:
                result.fields.setdefault("living_area_m2", _to_float(str(fa)))

            # Rooms
            if entry.get("numberOfRooms") is not None:
                result.fields.setdefault("rooms", _to_float(str(entry["numberOfRooms"])))

            # Price
            offers = entry.get("offers")
            if isinstance(offers, dict):
                p = offers.get("price")
                if p is not None:
                    result.fields.setdefault("price", _to_float(str(p)))
                cur = offers.get("priceCurrency")
                if cur:
                    result.fields.setdefault("currency", cur)

            # Images from JSON-LD (the most reliable source for property photos)
            ld_imgs = entry.get("image")
            if ld_imgs is not None:
                for img_url in _normalize_jsonld_image(ld_imgs):
                    absolute = urljoin(url, img_url)
                    if absolute in seen_images:
                        continue
                    if not _looks_like_property_image(absolute):
                        continue
                    seen_images.add(absolute)
                    result.image_urls.append(absolute)

        # Compose address from parts (use whatever subset we have)
        composed = _build_address(addr_parts)
        if composed:
            result.fields.setdefault("address", composed)
        if addr_parts.get("city"):
            result.fields.setdefault("city", addr_parts["city"])
        if addr_parts.get("postal"):
            result.fields.setdefault("postal_code", addr_parts["postal"])

        # ----- __NEXT_DATA__ / __NUXT__ / __INITIAL_STATE__ inline state -----
        # Many real estate sites embed structured data here with the full image gallery.
        for script in soup.find_all("script"):
            sid = script.get("id") or ""
            stype = script.get("type") or ""
            if sid in ("__NEXT_DATA__", "__NUXT_DATA__") or stype == "application/json":
                try:
                    data = json.loads(script.string or "")
                except (ValueError, TypeError):
                    continue
                _walk_for_image_urls(data, result.image_urls, seen_images, limit=60)

        # ----- Fallback regex extraction from page text -----
        text_blob = soup.get_text(" ", strip=True)
        if "price" not in result.fields:
            m = PRICE_RE.search(text_blob)
            if m:
                result.fields["price"] = _to_float(m.group("num"))
        if "living_area_m2" not in result.fields:
            m = AREA_RE.search(text_blob)
            if m:
                result.fields["living_area_m2"] = _to_float(m.group("num"))
        if "rooms" not in result.fields:
            m = ROOMS_RE.search(text_blob)
            if m:
                result.fields["rooms"] = _to_float(m.group("num"))

        # ----- OpenGraph images -----
        for og_url in _meta_all(soup, "og:image") + _meta_all(soup, "og:image:url") + _meta_all(soup, "twitter:image"):
            absolute = urljoin(url, og_url)
            if absolute in seen_images:
                continue
            if not _looks_like_property_image(absolute):
                continue
            seen_images.add(absolute)
            result.image_urls.append(absolute)

        # ----- HTML <img> / <picture> fallback -----
        # Only used to *supplement* if we found very few above, since this is the most noisy source.
        candidate_imgs: list[tuple[str, int]] = []  # (url, score)
        for img in soup.find_all(["img", "source"]):
            sources: list[str] = []
            # data-src takes precedence over src for lazy-loaded gallery images
            for attr in ("data-src", "data-lazy-src", "data-original", "src"):
                v = img.get(attr)
                if v:
                    sources.append(v)
            for srcset_attr in ("srcset", "data-srcset"):
                ss = img.get(srcset_attr)
                if ss:
                    # Pick the largest in the srcset
                    best_url, best_w = None, 0
                    for entry in ss.split(","):
                        bits = entry.strip().split()
                        if not bits:
                            continue
                        u = bits[0]
                        w = 0
                        if len(bits) > 1 and bits[1].endswith("w"):
                            try:
                                w = int(bits[1][:-1])
                            except ValueError:
                                w = 0
                        if w >= best_w:
                            best_url, best_w = u, w
                    if best_url:
                        sources.append(best_url)

            # Width/height hints from attrs
            try:
                w = int(img.get("width") or 0)
            except (TypeError, ValueError):
                w = 0
            try:
                h = int(img.get("height") or 0)
            except (TypeError, ValueError):
                h = 0
            score = (w * h) if (w and h) else 0
            # Penalize tiny images
            if (w and w < 200) or (h and h < 150):
                continue

            for src in sources:
                absolute = urljoin(url, src)
                if absolute in seen_images:
                    continue
                if not _looks_like_property_image(absolute):
                    continue
                candidate_imgs.append((absolute, score))

        # Add HTML candidates ordered by size hint (largest first)
        candidate_imgs.sort(key=lambda t: -t[1])
        for cu, _ in candidate_imgs:
            if cu in seen_images:
                continue
            seen_images.add(cu)
            result.image_urls.append(cu)

        # Cap total image count
        result.image_urls = result.image_urls[:50]

        result.text_snapshot = text_blob[:60_000]
        canon = soup.find("link", rel="canonical")
        if canon and canon.get("href"):
            result.canonical_url = urljoin(url, canon.get("href"))
        return result
