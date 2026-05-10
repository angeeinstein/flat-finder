"""Immobilienscout24.at (and .de) apartment listing importer.

Reads the Apollo GraphQL client cache that IS24 embeds as
  window.__APOLLO_STATE__=<JSON>
in a single inline <script> that also contains window.__INITIAL_STATE__ and
other assignments (one per line).  The real listing data lives under the key
"Expose:<expose_id>" in that object.
"""
from __future__ import annotations

import json
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from app.services.importer.base import ImporterResult
from app.services.importer.generic import GenericImporter, _looks_like_property_image


IS24_HOSTS = frozenset((
    "www.immobilienscout24.at",
    "immobilienscout24.at",
    "www.immobilienscout24.de",
    "immobilienscout24.de",
))
IS24_CDN_HOST = "pictures.immobilienscout24.de"
EXPOSE_ID_RE = re.compile(r"/expose/([a-zA-Z0-9]+)(?:[/?#]|$)")

_COUNTRY_CODE_MAP: dict[str, str] = {
    "AT": "Austria",
    "DE": "Germany",
    "CH": "Switzerland",
    "LI": "Liechtenstein",
}

_RENTAL_PERIOD_UNIT: dict[str, str] = {
    "YEAR": "Jahre",
    "MONTH": "Monate",
}


def _parse_euro_amount(s: str) -> float | None:
    if not s:
        return None
    s = re.sub(r"[€EUReur\s]", "", s)
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


def _parse_deposit_text(text: str, total_price: float | None) -> float | None:
    """Parse 'kaution: 3 bruttomonatsmieten' or '2 monatsmieten' → float."""
    m = re.search(r"(\d+(?:[.,]\d+)?)\s+(?:brutto)?monatsmiete[n]?", text.lower())
    if m and total_price:
        try:
            multiplier = float(m.group(1).replace(",", "."))
            return round(multiplier * total_price, 2)
        except ValueError:
            pass
    return None


def _is24_image_url(url: str) -> bool:
    """True for IS24 CDN URLs and URLs that pass the generic property-image heuristic."""
    if IS24_CDN_HOST in url:
        return True
    return _looks_like_property_image(url)


class ImmoScout24Importer(GenericImporter):
    name = "immoscout24"

    def can_handle(self, url: str) -> bool:
        return urlparse(url).netloc.lower() in IS24_HOSTS

    def extract(self, url: str, html: str, response) -> ImporterResult:
        result = super().extract(url, html, response)
        result.platform = "immoscout24"

        m = EXPOSE_ID_RE.search(urlparse(url).path)
        expose_id = m.group(1) if m else None
        if expose_id:
            result.external_id = expose_id
            host = urlparse(url).netloc.lower()
            result.canonical_url = f"https://{host}/expose/{expose_id}"

        result.fields.setdefault("country", "Austria")

        soup = BeautifulSoup(html, "lxml")
        apollo = self._parse_apollo_state(soup)
        if not apollo:
            return result

        expose = self._find_expose(apollo, expose_id)
        if not expose:
            return result

        self._extract_images(expose, result)
        self._extract_address(expose, result)
        self._extract_fields(expose, result)
        self._extract_description(expose, result)
        return result

    # ------------------------------------------------------------------ apollo

    def _parse_apollo_state(self, soup: BeautifulSoup) -> dict | None:
        for s in soup.find_all("script"):
            text = (s.string or "").strip()
            if "__APOLLO_STATE__" not in text:
                continue
            for line in text.split("\n"):
                m = re.match(r"window\.__APOLLO_STATE__\s*=\s*(.+)", line.strip())
                if not m:
                    continue
                raw = m.group(1).rstrip(";")
                try:
                    return json.loads(raw)
                except (ValueError, TypeError):
                    pass
        return None

    def _find_expose(self, apollo: dict, expose_id: str | None) -> dict | None:
        if expose_id:
            node = apollo.get(f"Expose:{expose_id}")
            if isinstance(node, dict):
                return node
        # Fallback: first Expose: key
        for k, v in apollo.items():
            if k.startswith("Expose:") and isinstance(v, dict):
                return v
        return None

    # ------------------------------------------------------------------ images

    def _extract_images(self, expose: dict, result: ImporterResult) -> None:
        seen: set[str] = set()
        gallery: list[str] = []

        for pic in (expose.get("pictures") or []):
            if isinstance(pic, dict):
                pic_url = pic.get("url") or pic.get("src") or ""
            elif isinstance(pic, str):
                pic_url = pic
            else:
                continue
            pic_url = pic_url.strip()
            if pic_url and pic_url not in seen and _is24_image_url(pic_url):
                seen.add(pic_url)
                gallery.append(pic_url)

        # attachments (sometimes floor plans end up here)
        for att in (expose.get("attachments") or []):
            if isinstance(att, dict):
                att_url = att.get("url") or att.get("src") or ""
                att_url = att_url.strip()
                if att_url and att_url not in seen and _is24_image_url(att_url):
                    seen.add(att_url)
                    gallery.append(att_url)

        if gallery:
            result.image_urls = gallery[:50]

    # ------------------------------------------------------------------ address

    def _extract_address(self, expose: dict, result: ImporterResult) -> None:
        loc = expose.get("localization") or {}
        addr = loc.get("address") or {}

        if isinstance(addr, dict):
            street = (addr.get("street") or "").strip()
            number = (addr.get("streetNumber") or "").strip()
            zip_code = (addr.get("zip") or "").strip() or None
            city = (addr.get("city") or "").strip() or None
            code = (addr.get("countryCode") or "").strip()
            country = _COUNTRY_CODE_MAP.get(code, code or None)

            if zip_code:
                result.fields["postal_code"] = zip_code
            if city:
                result.fields["city"] = city
            if country:
                result.fields["country"] = country

            if street:
                result.fields["address"] = (f"{street} {number}".strip() if number else street)
            else:
                # IS24.at often withholds the exact street for privacy
                result.fields["address_is_approximate"] = True

        info = loc.get("information") or {}
        floor_val = info.get("floor")
        if floor_val is not None:
            result.fields["floor"] = str(floor_val)

    # ------------------------------------------------------------------ fields

    def _extract_fields(self, expose: dict, result: ImporterResult) -> None:
        area = expose.get("area") or {}
        if area.get("livingArea") is not None:
            result.fields["living_area_m2"] = float(area["livingArea"])
        if area.get("numberOfRooms") is not None:
            result.fields["rooms"] = float(area["numberOfRooms"])
        if area.get("cellarArea"):
            result.fields["has_cellar"] = True

        outdoor = area.get("outdoorSpaces") or []
        if "BALCONY" in outdoor:
            result.fields["has_balcony"] = True
        if "TERRACE" in outdoor:
            result.fields["has_terrace"] = True
        if "GARDEN" in outdoor or "GARDEN_AREA" in outdoor:
            result.fields["has_garden"] = True

        # ---- pricing ----
        price_info = expose.get("priceInformation") or {}
        primary_price = price_info.get("primaryPrice")
        if primary_price is not None:
            result.fields["total_monthly_cost"] = float(primary_price)

        if price_info.get("hasCommission") is False:
            result.fields["commission"] = 0.0

        # Granular cost breakdown: extract net rent and operating costs separately.
        # IS24 running costs: Miete / USt.Miete / Betriebskosten / USt.Betriebskosten
        # Always override any value set by the generic extractor's text regex.
        costs = expose.get("costs") or {}
        extracted_price: float | None = None
        extracted_opex: float | None = None
        for item in (costs.get("running") or []):
            if not isinstance(item, dict):
                continue
            label = (item.get("label") or "").lower()
            val = _parse_euro_amount(item.get("price") or "")
            if val is None:
                continue
            if label == "miete":
                extracted_price = val
            elif label == "betriebskosten":
                extracted_opex = val

        if extracted_price is not None:
            result.fields["price"] = extracted_price
        elif primary_price is not None:
            result.fields["price"] = float(primary_price)

        if extracted_opex is not None:
            result.fields["operating_costs"] = extracted_opex

        # Deposit from one-time costs
        primary_price_float = float(primary_price) if primary_price is not None else None
        for item in (costs.get("oneTime") or []):
            if not isinstance(item, dict):
                continue
            text = item.get("text") or ""
            dep = _parse_deposit_text(text, primary_price_float)
            if dep is not None:
                result.fields.setdefault("deposit", dep)

        # ---- fitting ----
        fitting = expose.get("fitting") or {}
        parking = fitting.get("numberOfParkingSpaces")
        if parking is not None:
            try:
                if int(parking) > 0:
                    result.fields["has_parking"] = True
            except (TypeError, ValueError):
                pass

        # ---- condition ----
        condition = expose.get("condition") or {}
        heating_labels = [
            ht["label"]
            for ht in (condition.get("heatingTypes") or [])
            if isinstance(ht, dict) and ht.get("label")
        ]
        if heating_labels:
            result.fields["heating_type"] = ", ".join(heating_labels)

        energy = condition.get("energyCertification") or {}
        energy_parts: list[str] = []
        hd = (energy.get("heatingDemand") or {}).get("value")
        hdc = (energy.get("heatingDemandClass") or {}).get("value")
        if hd:
            energy_parts.append(f"HWB {hd} kWh/m²a")
        if hdc:
            energy_parts.append(f"Klasse {hdc}")
        if energy_parts:
            result.fields["energy_cert_info"] = ", ".join(energy_parts)

        # ---- lease / availability ----
        obj = expose.get("object") or {}
        rental_period = obj.get("rentalPeriod")
        rental_type = obj.get("rentalPeriodType")
        if rental_type == "UNLIMITED":
            result.fields["lease_duration_limited"] = False
        elif rental_type:
            result.fields["lease_duration_limited"] = True
            if rental_period:
                unit = _RENTAL_PERIOD_UNIT.get(rental_type, rental_type)
                result.fields["lease_duration_text"] = f"{rental_period} {unit}"

        # ---- contact ----
        contact = expose.get("contact") or {}
        if contact.get("fullName"):
            result.fields["contact_name"] = contact["fullName"]
        company = contact.get("company") or {}
        contact_parts: list[str] = []
        if contact.get("contactPhone"):
            contact_parts.append(contact["contactPhone"])
        if company.get("name"):
            contact_parts.append(company["name"])
        if contact_parts:
            result.fields["contact_info"] = " | ".join(contact_parts)

    # ------------------------------------------------------------------ description

    def _extract_description(self, expose: dict, result: ImporterResult) -> None:
        desc = expose.get("description") or {}
        parts: list[str] = []
        main = desc.get("descriptionNote") or ""
        if main:
            parts.append(main)
        for key in ("locationNote", "miscellaneousNote", "fittingNote"):
            val = desc.get(key) or ""
            if val and val not in parts:
                parts.append(val)
        if not parts:
            return
        full_html = "\n\n".join(parts)
        plain = BeautifulSoup(full_html, "lxml").get_text(separator="\n", strip=True)
        result.fields["description"] = plain
        result.text_snapshot = plain
