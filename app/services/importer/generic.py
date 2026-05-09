"""Generic fallback importer using BeautifulSoup, JSON-LD, OpenGraph and meta tags."""
from __future__ import annotations

import json
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from app.services.importer.base import ImporterBase, ImporterResult


PRICE_RE = re.compile(r"(?P<num>[\d.,]+)\s*(?:€|EUR)", re.IGNORECASE)
AREA_RE = re.compile(r"(?P<num>\d{1,4}(?:[.,]\d+)?)\s*m²", re.IGNORECASE)
ROOMS_RE = re.compile(r"(?P<num>\d{1,2}(?:[.,]\d+)?)\s*(?:Zimmer|rooms?)", re.IGNORECASE)


def _to_float(s: str) -> float | None:
    if s is None:
        return None
    s = s.strip().replace(" ", "")
    # German: 1.234,56 → 1234.56; English: 1,234.56 → 1234.56
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
        return tag.get("content").strip() or None
    return None


def _jsonld(soup: BeautifulSoup) -> list[dict]:
    out = []
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
            # @graph holders
            graph = data.get("@graph")
            if isinstance(graph, list):
                out.extend(g for g in graph if isinstance(g, dict))
    return out


class GenericImporter(ImporterBase):
    name = "generic"

    def can_handle(self, url: str) -> bool:
        return True  # always last-resort

    def extract(self, url: str, html: str, response) -> ImporterResult:
        soup = BeautifulSoup(html, "lxml")
        result = ImporterResult(platform=urlparse(url).netloc)

        # Title
        title = _meta(soup, "og:title")
        if not title and soup.title and soup.title.string:
            title = soup.title.string.strip()
        if title:
            result.fields["title"] = title[:500]

        # Description
        desc = _meta(soup, "og:description") or _meta(soup, "description")
        if desc:
            result.fields["description"] = desc

        # JSON-LD
        ld_data = _jsonld(soup)
        for entry in ld_data:
            t = entry.get("@type")
            types = t if isinstance(t, list) else [t]
            if any(x in ("Apartment", "Residence", "Place", "Product", "Offer", "RealEstateListing") for x in types if x):
                # Address
                addr = entry.get("address")
                if isinstance(addr, dict):
                    parts = [
                        addr.get("streetAddress"),
                        addr.get("postalCode"),
                        addr.get("addressLocality"),
                    ]
                    parts = [p for p in parts if p]
                    if parts:
                        result.fields.setdefault("address", " ".join(parts)[:500])
                    if addr.get("addressLocality"):
                        result.fields.setdefault("city", addr["addressLocality"])
                    if addr.get("postalCode"):
                        result.fields.setdefault("postal_code", str(addr["postalCode"]))
                    if addr.get("addressCountry"):
                        country = addr["addressCountry"]
                        if isinstance(country, dict):
                            country = country.get("name") or country.get("alternateName")
                        if country:
                            result.fields.setdefault("country", country)
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
                # Rooms
                if entry.get("numberOfRooms") is not None:
                    result.fields.setdefault("rooms", _to_float(str(entry["numberOfRooms"])))
                # Price (Offer)
                offers = entry.get("offers")
                if isinstance(offers, dict):
                    p = offers.get("price")
                    if p is not None:
                        result.fields.setdefault("price", _to_float(str(p)))
                    cur = offers.get("priceCurrency")
                    if cur:
                        result.fields.setdefault("currency", cur)

        # Fallback regex-based extraction from page text
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

        # Images: prefer og:image, then largest <img> in main content
        seen: set[str] = set()
        og_img = _meta(soup, "og:image")
        if og_img:
            absolute = urljoin(url, og_img)
            if absolute not in seen:
                result.image_urls.append(absolute)
                seen.add(absolute)
        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src") or ""
            if not src:
                continue
            if src.startswith("data:"):
                continue
            absolute = urljoin(url, src)
            if absolute in seen:
                continue
            seen.add(absolute)
            result.image_urls.append(absolute)
        result.image_urls = result.image_urls[:30]  # cap

        result.text_snapshot = text_blob[:60_000]
        # Canonical
        canon = soup.find("link", rel="canonical")
        if canon and canon.get("href"):
            result.canonical_url = urljoin(url, canon.get("href"))
        return result
