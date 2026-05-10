"""Immowelt.at (and .de) apartment listing importer.

Reads the `window["__UFRN_LIFECYCLE_SERVERREQUEST__"]=JSON.parse(...)` payload
embedded as a double-JSON-encoded inline script tag.  The listing data lives
under data["app_cldp"]["data"]["classified"].
"""
from __future__ import annotations

import html as html_mod
import json
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from app.services.importer.base import ImporterResult
from app.services.importer.generic import GenericImporter, _looks_like_property_image


IMMOWELT_HOSTS = frozenset((
    "www.immowelt.at",
    "immowelt.at",
    "www.immowelt.de",
    "immowelt.de",
))

EXPOSE_ID_RE = re.compile(
    r"/expose/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
    re.IGNORECASE,
)

_COUNTRY_CODE_MAP: dict[str, str] = {
    "AUT": "Austria",
    "DEU": "Germany",
    "CHE": "Switzerland",
}

_DEPOSIT_MULTIPLIER_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s+(?:brutto)?monatsmiete[n]?",
    re.IGNORECASE,
)


def _parse_aria_price(aria: str | None) -> float | None:
    """Parse an ariaLabel like '1229.93 €' — already in English decimal format."""
    if not aria:
        return None
    s = re.sub(r"[€EUReur\s\xa0]", "", aria)
    try:
        return float(s)
    except ValueError:
        return None


def _parse_german_amount(s: str | None) -> float | None:
    """Parse German-formatted euro amounts like '5.970,00 €' or '9.500 EUR'."""
    if not s:
        return None
    s = html_mod.unescape(s).strip()
    s = re.sub(r"[€EUReur\s\xa0]", "", s)
    if not s:
        return None
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    elif "." in s:
        after = s.rsplit(".", 1)[-1]
        if len(after) == 3 and after.isdigit():
            s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


def _parse_deposit(text: str, total_price: float | None) -> float | None:
    """Parse deposit text: 'N Bruttomonatsmieten' → N × total, else try as amount."""
    text_clean = html_mod.unescape(text or "").strip()
    m = _DEPOSIT_MULTIPLIER_RE.search(text_clean.lower())
    if m and total_price:
        try:
            mult = float(m.group(1).replace(",", "."))
            return round(mult * total_price, 2)
        except ValueError:
            pass
    return _parse_german_amount(text_clean)


def _parse_german_float(s: str | None) -> float | None:
    """Parse '96,2' or '4,5' (German decimal comma) to float."""
    if not s:
        return None
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return None


class ImmoweltImporter(GenericImporter):
    name = "immowelt"

    def can_handle(self, url: str) -> bool:
        return urlparse(url).netloc.lower() in IMMOWELT_HOSTS

    def extract(self, url: str, html: str, response) -> ImporterResult:
        result = super().extract(url, html, response)
        result.platform = "immowelt"

        m = EXPOSE_ID_RE.search(urlparse(url).path)
        if m:
            result.external_id = m.group(1).lower()
            host = urlparse(url).netloc.lower()
            result.canonical_url = f"https://{host}/expose/{result.external_id}"

        result.fields.setdefault("country", "Austria")

        soup = BeautifulSoup(html, "lxml")
        classified = self._parse_classified(soup)
        if not classified:
            return result

        sections = classified.get("sections") or {}
        domains = classified.get("domains") or {}
        tags = classified.get("tags") or {}
        contact_sec = classified.get("contactSections") or {}

        self._extract_images(sections, domains, result)
        self._extract_location(sections, result)
        self._extract_price(sections, tags, result)
        self._extract_hard_facts(sections, result)
        self._extract_features(sections, result)
        self._extract_energy(sections, result)
        self._extract_description(sections, result)
        self._extract_contact(contact_sec, result)
        return result

    # ------------------------------------------------------------------ parser

    def _parse_classified(self, soup: BeautifulSoup) -> dict | None:
        for s in soup.find_all("script"):
            text = (s.string or "").strip()
            if "__UFRN_LIFECYCLE_SERVERREQUEST__" not in text:
                continue
            m = re.match(
                r'window\["__UFRN_LIFECYCLE_SERVERREQUEST__"\]=JSON\.parse\((.+)\);\s*$',
                text,
            )
            if not m:
                continue
            try:
                data = json.loads(json.loads(m.group(1)))
                return data["app_cldp"]["data"]["classified"]
            except (ValueError, TypeError, KeyError):
                pass
        return None

    # ------------------------------------------------------------------ images

    def _extract_images(
        self, sections: dict, domains: dict, result: ImporterResult
    ) -> None:
        seen: set[str] = set()
        gallery: list[str] = []

        medias = (domains.get("medias") or {})
        gallery_imgs = (sections.get("gallery") or {}).get("images") or []
        floorplans = medias.get("floorplans") or []

        for img in gallery_imgs + floorplans:
            url = (img.get("url") or "").strip() if isinstance(img, dict) else ""
            if url and url not in seen and _looks_like_property_image(url):
                seen.add(url)
                gallery.append(url)

        if gallery:
            result.image_urls = gallery[:50]

    # ------------------------------------------------------------------ location

    def _extract_location(self, sections: dict, result: ImporterResult) -> None:
        loc = sections.get("location") or {}
        addr = loc.get("address") or {}

        street = (addr.get("street") or "").strip() or None
        zip_code = (addr.get("zipCode") or "").strip() or None
        city = (addr.get("city") or "").strip() or None
        country_code = (addr.get("country") or "").strip()
        country = _COUNTRY_CODE_MAP.get(country_code, country_code or None)

        is_published = loc.get("isAddressPublished", True)
        if not is_published or not street:
            result.fields["address_is_approximate"] = True
            result.fields.pop("address", None)  # discard generic extractor's guess
        if street:
            result.fields["address"] = street
        if zip_code:
            result.fields["postal_code"] = zip_code
        if city:
            result.fields["city"] = city
        if country:
            result.fields["country"] = country

        # Coordinates: GeoJSON order is [lng, lat]
        coords = (loc.get("geometry") or {}).get("coordinates") or []
        if len(coords) == 2:
            try:
                result.fields["lng"] = float(coords[0])
                result.fields["lat"] = float(coords[1])
            except (TypeError, ValueError):
                pass

    # ------------------------------------------------------------------ price

    def _extract_price(
        self, sections: dict, tags: dict, result: ImporterResult
    ) -> None:
        price_sec = sections.get("price") or {}
        breakdown = price_sec.get("breakdown") or {}

        # Parse breakdown groups by label
        net_rent: float | None = None
        operating_costs: float | None = None
        for group in (breakdown.get("groups") or []):
            label_raw = (group.get("label") or {})
            label = label_raw.get("main", "") if isinstance(label_raw, dict) else str(label_raw)
            aria = ((group.get("value") or {}).get("main") or {}).get("ariaLabel")
            val = _parse_aria_price(aria)
            if val is None:
                continue
            low = label.lower()
            if "nettokaltmiete" in low or "nettomiete" in low:
                net_rent = val
            elif "betriebskosten" in low:
                operating_costs = val

        total_aria = (breakdown.get("total") or {}).get("ariaLabel")
        total = _parse_aria_price(total_aria)

        # Fall back: try base.main ariaLabel
        if net_rent is None:
            base_aria = (
                (price_sec.get("base") or {}).get("main") or {}
            ).get("value", {}).get("main", {}).get("ariaLabel")
            net_rent = _parse_aria_price(base_aria)

        if net_rent is not None:
            result.fields["price"] = net_rent
        elif total is not None:
            result.fields["price"] = total

        if operating_costs is not None:
            result.fields["operating_costs"] = operating_costs

        if total is not None:
            result.fields["total_monthly_cost"] = total

        # Deposit
        for add in (price_sec.get("additional") or []):
            dep_text = add.get("text") or ""
            dep = _parse_deposit(dep_text, total)
            if dep is not None:
                result.fields.setdefault("deposit", dep)
                break

        # Commission
        has_brokerage = tags.get("hasBrokerageFee")
        if has_brokerage is False:
            result.fields.setdefault("commission", 0.0)

    # ------------------------------------------------------------------ hard facts

    def _extract_hard_facts(self, sections: dict, result: ImporterResult) -> None:
        hf = sections.get("hardFacts") or {}
        for fact in (hf.get("facts") or []):
            t = fact.get("type", "")
            v = fact.get("splitValue", "")
            if t == "numberOfRooms":
                rooms = _parse_german_float(v)
                if rooms is not None:
                    result.fields["rooms"] = rooms
            elif t == "livingSpace":
                area = _parse_german_float(v)
                if area is not None:
                    result.fields["living_area_m2"] = area
            elif t == "numberOfFloors":
                result.fields.setdefault("floor", v.rstrip("."))

    # ------------------------------------------------------------------ features

    def _extract_features(self, sections: dict, result: ImporterResult) -> None:
        feat = sections.get("features") or {}
        for item in (feat.get("preview") or []):
            icon = item.get("icon", "")
            val = (item.get("value") or "").lower()
            if icon == "balcony" or "balkon" in val:
                result.fields.setdefault("has_balcony", True)
            if icon == "terrace" or "terrasse" in val:
                result.fields.setdefault("has_terrace", True)
            if icon == "cellar" or "keller" in val:
                result.fields.setdefault("has_cellar", True)
            if icon == "parking-lots" or "garage" in val or "stellplatz" in val or "parkplatz" in val:
                result.fields.setdefault("has_parking", True)
            if icon == "garden" or "garten" in val:
                result.fields.setdefault("has_garden", True)
            if "loggia" in val:
                result.fields.setdefault("has_balcony", True)

    # ------------------------------------------------------------------ energy

    def _extract_energy(self, sections: dict, result: ImporterResult) -> None:
        energy = sections.get("energy") or {}

        for ef in (energy.get("features") or []):
            t = ef.get("type", "")
            v = ef.get("value", "")
            if t == "heatingSystem" and v:
                result.fields.setdefault("heating_type", v)

        energy_parts: list[str] = []
        for cert in (energy.get("certificates") or []):
            for scale in (cert.get("scales") or []):
                ec = scale.get("efficiencyClass") or {}
                rating = ec.get("rating")
                vals = scale.get("values") or []
                name = scale.get("name", "")
                val_str = vals[0].get("value", "") if vals else ""
                if "HWB" in name or "Heizwärme" in name or "Heizw" in name:
                    if val_str:
                        energy_parts.append(f"HWB {val_str}")
                    if rating:
                        energy_parts.append(f"Klasse {rating}")
                elif "fGEE" in name or "Gesamtenergie" in name:
                    if val_str and val_str != "-":
                        energy_parts.append(f"fGEE {val_str}")

        if energy_parts:
            result.fields.setdefault("energy_cert_info", ", ".join(energy_parts))

    # ------------------------------------------------------------------ description

    def _extract_description(self, sections: dict, result: ImporterResult) -> None:
        parts: list[str] = []

        main_desc = (sections.get("mainDescription") or {}).get("description") or ""
        if main_desc:
            parts.append(main_desc)

        area_desc = (sections.get("areaDescription") or {}).get("description") or ""
        area_head = (sections.get("areaDescription") or {}).get("headline") or "Lage"
        if area_desc and area_desc not in parts:
            parts.append(f"<strong>{area_head}</strong>\n{area_desc}")

        ext_desc = (sections.get("extendedInfoDescription") or {}).get("description") or ""
        ext_head = (sections.get("extendedInfoDescription") or {}).get("headline") or "Weitere Informationen"
        if ext_desc and ext_desc not in parts:
            parts.append(f"<strong>{ext_head}</strong>\n{ext_desc}")

        if not parts:
            return

        full_html = "\n\n".join(parts)
        plain = BeautifulSoup(full_html, "lxml").get_text(separator="\n", strip=True)
        result.fields["description"] = plain
        result.text_snapshot = plain

    # ------------------------------------------------------------------ contact

    def _extract_contact(self, contact_sec: dict, result: ImporterResult) -> None:
        cc = contact_sec.get("contactCard") or {}
        person = (cc.get("subtitle") or "").strip() or None
        company = (cc.get("title") or "").strip() or None

        if person:
            result.fields.setdefault("contact_name", person)

        phones = (contact_sec.get("static") or {}).get("phoneNumbers") or []
        seen_phones: set[str] = set()
        unique_phones: list[str] = []
        for p in phones:
            if p and p not in seen_phones:
                seen_phones.add(p)
                unique_phones.append(p)
        contact_parts = unique_phones
        if company:
            contact_parts.append(company)
        if contact_parts:
            result.fields.setdefault("contact_info", " | ".join(contact_parts))
