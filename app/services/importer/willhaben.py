"""Willhaben.at apartment listing importer.

Builds on the generic importer's JSON-LD/OpenGraph extraction and adds
Willhaben-specific parsing of the Next.js __NEXT_DATA__ payload, which is
the authoritative source for images, attributes, address, and description.
"""
from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from app.services.importer.generic import GenericImporter, _looks_like_property_image
from app.services.importer.base import ImporterResult


WILLHABEN_HOSTS = ("www.willhaben.at", "willhaben.at")
EXTERNAL_ID_RE = re.compile(r"(?:^|[/\-_])(\d{6,})(?:[/?#]|$)")
WILLHABEN_IMG_HOSTS = ("cache.willhaben.at", "bilder.willhaben.at", "willhaben.scdn.cloud")

# German → English country name mapping used for the country field
_COUNTRY_DE_EN: dict[str, str] = {
    "Österreich": "Austria",
    "oesterreich": "Austria",
    "Deutschland": "Germany",
    "Schweiz": "Switzerland",
}


def _walk(node: Any, key: str, out: list[Any]) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            if k == key:
                out.append(v)
            _walk(v, key, out)
    elif isinstance(node, list):
        for v in node:
            _walk(v, key, out)


class WillhabenImporter(GenericImporter):
    name = "willhaben"

    def can_handle(self, url: str) -> bool:
        host = urlparse(url).netloc.lower()
        return host in WILLHABEN_HOSTS

    def extract(self, url: str, html: str, response) -> ImporterResult:
        result = super().extract(url, html, response)
        result.platform = "willhaben"

        # External ID: long numeric segment in the URL path
        m = EXTERNAL_ID_RE.search(urlparse(url).path)
        if m:
            result.external_id = m.group(1)

        result.fields.setdefault("country", "Austria")

        soup = BeautifulSoup(html, "lxml")
        next_data_tag = soup.find("script", id="__NEXT_DATA__")
        if not (next_data_tag and next_data_tag.string):
            return result

        try:
            data = json.loads(next_data_tag.string)
        except (ValueError, TypeError):
            return result

        # advertDetails is the canonical payload for real-estate listings
        ad: dict = (
            data.get("props", {}).get("pageProps", {}).get("advertDetails") or {}
        )

        self._extract_willhaben_images(data, ad, url, result)
        self._extract_willhaben_address_details(ad, result)
        self._extract_willhaben_attrs(data, ad, result)
        self._extract_willhaben_description(ad, result)
        return result

    # ------------------------------------------------------------------ images

    def _extract_willhaben_images(
        self, data: Any, ad: dict, base_url: str, result: ImporterResult
    ) -> None:
        seen: set[str] = set()
        gallery: list[str] = []

        # Primary source: advertImageList contains both regular photos AND
        # floor plans in sibling lists.  We must iterate ALL sub-lists instead
        # of stopping at the first non-empty one (previous bug).
        ail = ad.get("advertImageList")
        if isinstance(ail, dict):
            # Defined sub-list keys in priority order: regular photos first,
            # then floor plans so the floor plan appears at the end.
            for sub in ("advertImage", "floorPlans", "imageList", "photos", "items"):
                for item in (ail.get(sub) or []):
                    self._ingest_image_item(item, base_url, seen, gallery)

        # Fallback: walk the full Next.js state tree for any image-list node
        # (covers edge cases like motor listings or different page layouts).
        if len(gallery) < 8:
            for top_key in ("advertImageList", "imageList", "photos", "advertImages", "attachments"):
                buckets: list[Any] = []
                _walk(data, top_key, buckets)
                for bucket in buckets:
                    if isinstance(bucket, dict):
                        for sub in ("advertImage", "floorPlans", "imageList",
                                    "attachment", "photos", "items"):
                            for item in (bucket.get(sub) or []):
                                self._ingest_image_item(item, base_url, seen, gallery)
                    elif isinstance(bucket, list):
                        for item in bucket:
                            self._ingest_image_item(item, base_url, seen, gallery)

        # Last resort: scan every string value in the state for CDN URLs
        if len(gallery) < 8:
            self._collect_image_urls(data, gallery, seen)

        if gallery:
            result.image_urls = gallery[:50]

    def _ingest_image_item(
        self, item: Any, base_url: str, seen: set[str], out: list[str]
    ) -> None:
        if isinstance(item, str):
            self._add_url(item, base_url, seen, out)
        elif isinstance(item, dict):
            # Prefer full-size reference over compressed main image
            for k in ("referenceImageUrl", "mainImageUrl", "url",
                      "fullSizeUrl", "originalUrl", "src"):
                v = item.get(k)
                if isinstance(v, str):
                    self._add_url(v, base_url, seen, out)
                    break

    def _add_url(self, src: str, base_url: str, seen: set[str], out: list[str]) -> None:
        absolute = urljoin(base_url, src)
        if absolute in seen:
            return
        if not _looks_like_property_image(absolute):
            return
        seen.add(absolute)
        out.append(absolute)

    def _collect_image_urls(self, node: Any, out: list[str], seen: set[str]) -> None:
        if isinstance(node, str):
            if any(h in node for h in WILLHABEN_IMG_HOSTS) and node not in seen:
                if _looks_like_property_image(node):
                    seen.add(node)
                    out.append(node)
        elif isinstance(node, dict):
            for v in node.values():
                self._collect_image_urls(v, out, seen)
        elif isinstance(node, list):
            for v in node:
                self._collect_image_urls(v, out, seen)

    # ------------------------------------------------------------------ address

    def _extract_willhaben_address_details(
        self, ad: dict, result: ImporterResult
    ) -> None:
        """Read from `advertAddressDetails` — the most reliable address source.

        This always overrides whatever the generic extractor guessed, because
        the generic extractor often picks up junk from the title/description
        (e.g. "Sonnige 4" from "Sonnige 4-Zimmer-Wohnung…").

        Structure (confirmed from live listing):
          addressLines.value: ["Hackenberggasse 22-24", "Wien"]
          postCode:   "1190"
          postalName: "Wien, 19. Bezirk, Döbling"
          province:   "Wien"
          country:    "Österreich"
        """
        aad = ad.get("advertAddressDetails")
        if not isinstance(aad, dict):
            return

        addr_lines_raw = aad.get("addressLines") or {}
        lines = addr_lines_raw.get("value", []) if isinstance(addr_lines_raw, dict) else []
        street = lines[0].strip() if lines else None

        postcode = (aad.get("postCode") or "").strip() or None
        province = (aad.get("province") or "").strip() or None  # e.g. "Wien"
        country_raw = (aad.get("country") or "").strip()
        country_en = _COUNTRY_DE_EN.get(country_raw, country_raw or None)

        # Detect district-only values like "Wien, 14. Bezirk, Penzing" — sellers can
        # blur their map location, leaving only a district name in addressLines[0].
        if street and ("Bezirk" in street or street.startswith(("Wien,", "Graz,", "Linz,", "Salzburg,"))):
            result.fields["address_is_approximate"] = True
            result.fields.pop("address", None)  # discard any guess from the generic extractor
            street = None  # don't store the district label as an address

        # Always override — advertAddressDetails is authoritative for Willhaben
        if street:
            result.fields["address"] = street
        if postcode:
            result.fields["postal_code"] = postcode
        if province:
            result.fields["city"] = province
        if country_en:
            result.fields["country"] = country_en

    def _extract_willhaben_attrs(
        self, data: Any, ad: dict, result: ImporterResult
    ) -> None:
        """Read structured attributes for address fallback, coordinates, and price details."""
        attrs = self._collect_willhaben_attrs(data)
        if not attrs:
            return

        def first(*keys: str) -> str | None:
            for k in keys:
                v = attrs.get(k)
                if v:
                    return v
            return None

        # Address fallback (LOCATION/* attribute names are the live format)
        street = first(
            "LOCATION/ADDRESS_1",
            "ADDRESS", "ADDRESS_2", "STREET", "STREET_NAME",
            "ESTATE_PREMIUM_HOUSE_NUMBER", "OBJECT_ADDRESS",
            "REAL_ESTATE_OBJECT_ADDRESS",
        )
        postal = first(
            "POSTCODE", "POST_CODE", "ZIP_CODE", "ZIP", "POSTAL_CODE", "PLZ",
        )
        city = first(
            "LOCATION/ADDRESS_2",
            "LOCATION", "CITY", "TOWN", "ORT", "DISTRICT_OF_VIENNA",
        )
        state = first("STATE", "BUNDESLAND", "FEDERAL_STATE")
        district = first("DISTRICT", "DISTRICT_LEVEL_1", "DISTRICT_LEVEL_2", "BEZIRK")

        if not result.fields.get("postal_code") and postal:
            result.fields["postal_code"] = postal
        if not result.fields.get("city") and city:
            result.fields["city"] = city
        if not result.fields.get("address") and street:
            parts = [street]
            loc2 = " ".join(p for p in (postal, city) if p)
            if loc2:
                parts.append(loc2)
            if district or state:
                parts.append(district or state)  # type: ignore[arg-type]
            result.fields["address"] = ", ".join(parts)[:500]

        # Direct coordinates from the COORDINATES attribute — always prefer over geocoding
        coords_str = first("COORDINATES")
        if coords_str:
            parts_c = coords_str.split(",")
            if len(parts_c) == 2:
                try:
                    result.fields["lat"] = float(parts_c[0].strip())
                    result.fields["lng"] = float(parts_c[1].strip())
                except ValueError:
                    pass

        # ---- Floor ----
        floor_val = first("FLOOR")
        if floor_val:
            result.fields.setdefault("floor", floor_val)

        # ---- Heating ----
        heating = first("HEATING")
        if heating:
            result.fields.setdefault("heating_type", heating)

        # ---- Energy certificate ----
        hwb = first("ENERGY_HWB")
        hwb_class = first("ENERGY_HWB_CLASS")
        fgee = first("ENERGY_FGEE")
        fgee_class = first("ENERGY_FGEE_CLASS")
        energy_parts: list[str] = []
        if hwb:
            energy_parts.append(f"HWB {hwb} kWh/m²a")
        if hwb_class:
            energy_parts.append(f"Klasse {hwb_class}")
        if fgee:
            energy_parts.append(f"fGEE {fgee}")
        if energy_parts:
            result.fields.setdefault("energy_cert_info", ", ".join(energy_parts))

        # ---- Lease duration ----
        term_limit = first("DURATION/HASTERMLIMIT")
        if term_limit:
            is_limited = term_limit.lower() in ("befristet", "true", "1", "yes")
            result.fields.setdefault("lease_duration_limited", is_limited)
        term_text = first("DURATION/TERMLIMITTEXT")
        if term_text:
            result.fields.setdefault("lease_duration_text", term_text)

        # ---- Deposit ----
        deposit_raw = first("ADDITIONAL_COST/DEPOSIT")
        if deposit_raw:
            try:
                result.fields.setdefault("deposit", float(deposit_raw.replace(",", ".")))
            except ValueError:
                pass

        # ---- Operating costs ----
        opex_raw = first("RENTAL_PRICE/ADDITIONAL_COST_NET", "RENTAL_PRICE/ADDITIONAL_COSTS_NET")
        if opex_raw:
            try:
                result.fields.setdefault(
                    "operating_costs", float(opex_raw.replace(".", "").replace(",", "."))
                )
            except ValueError:
                pass

        # ---- Commission ----
        fee_text = first("ADDITIONAL_COST/FEE") or ""
        if fee_text:
            lower_fee = fee_text.lower()
            if any(kw in lower_fee for kw in ("provisionsfrei", "erstauftraggeberprinzip", "keine provision")):
                result.fields.setdefault("commission", 0.0)

        # ---- Outdoor spaces ----
        area_type = first("FREE_AREA/FREE_AREA_TYPE", "FREE_AREA_TYPE")
        if area_type:
            lower = area_type.lower()
            if "balkon" in lower:
                result.fields.setdefault("has_balcony", True)
            if "terrasse" in lower:
                result.fields.setdefault("has_terrace", True)
            if "garten" in lower or "garden" in lower:
                result.fields.setdefault("has_garden", True)
            if "loggia" in lower:
                result.fields.setdefault("has_balcony", True)

        # ---- Contact ----
        contact_name = first("CONTACT/NAME")
        if contact_name:
            result.fields.setdefault("contact_name", contact_name)
        phone = first("CONTACT/PHONE")
        company = first("CONTACT/COMPANYNAME", "CONTACT/COMPANY")
        contact_parts = [p for p in (phone, company) if p]
        if contact_parts:
            result.fields.setdefault("contact_info", " | ".join(contact_parts))

    # ------------------------------------------------------------------ description

    def _extract_willhaben_description(self, ad: dict, result: ImporterResult) -> None:
        """Assemble the full listing description from structured attribute sections."""
        attrs_by_name: dict[str, str] = {}
        for r in (ad.get("attributes", {}).get("attribute") or []):
            name = r.get("name", "")
            vals = r.get("values") or []
            if vals and isinstance(vals[0], str):
                attrs_by_name[name] = vals[0]

        # Main body
        parts: list[str] = []
        main_desc = attrs_by_name.get("DESCRIPTION", "")
        if main_desc:
            parts.append(main_desc)

        # Labelled sub-sections (Lage, Sonstiges, …)
        for k, v in attrs_by_name.items():
            if k.startswith("GENERAL_TEXT_ADVERT/") and v:
                section_label = k.split("/", 1)[1].replace("_", " ").title()
                parts.append(f"<strong>{section_label}</strong>\n{v}")

        if not parts:
            return

        full_html = "\n\n".join(parts)
        plain = BeautifulSoup(full_html, "lxml").get_text(separator="\n", strip=True)

        # Always override the generic extractor's short OG/JSON-LD description
        # with the full structured text from Willhaben's attribute payload.
        result.fields["description"] = plain
        result.text_snapshot = plain

    # ------------------------------------------------------------------ attrs walker

    def _collect_willhaben_attrs(self, data: Any) -> dict[str, str]:
        """Walk every dict in the Next.js payload and harvest uppercase name→value pairs."""
        out: dict[str, str] = {}

        def visit(node: Any) -> None:
            if isinstance(node, dict):
                # Shape A: {"name": "POSTCODE", "values": ["1190"]}
                name = node.get("name")
                if isinstance(name, str) and name.isupper():
                    values = node.get("values") or node.get("value")
                    if isinstance(values, list) and values:
                        v = values[0]
                        if isinstance(v, (str, int)):
                            out.setdefault(name, str(v))
                    elif isinstance(values, (str, int)):
                        out.setdefault(name, str(values))
                # Shape B: {"key": "POSTCODE", "value": "1190"}
                key = node.get("key")
                if isinstance(key, str) and key.isupper():
                    val = node.get("value") or node.get("formattedValue")
                    if isinstance(val, (str, int)):
                        out.setdefault(key, str(val))
                for v in node.values():
                    visit(v)
            elif isinstance(node, list):
                for v in node:
                    visit(v)

        visit(data)
        return out
