"""Willhaben.at apartment listing importer.

Builds on the generic importer's JSON-LD/OpenGraph extraction and adds
Willhaben-specific touches (URL pattern, external ID, Next.js image gallery).
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

        # External ID: long numeric segment in path
        m = EXTERNAL_ID_RE.search(urlparse(url).path)
        if m:
            result.external_id = m.group(1)

        # Default country
        result.fields.setdefault("country", "Austria")

        # Willhaben uses Next.js — pull all images from the embedded state.
        # The advert payload contains "advertImageList" with full-size URLs.
        soup = BeautifulSoup(html, "lxml")
        next_data_tag = soup.find("script", id="__NEXT_DATA__")
        if next_data_tag and next_data_tag.string:
            try:
                data = json.loads(next_data_tag.string)
            except (ValueError, TypeError):
                data = None
            if data is not None:
                self._extract_willhaben_images(data, url, result)
                self._extract_willhaben_address(data, result)
        return result

    def _extract_willhaben_images(self, data: Any, base_url: str, result: ImporterResult) -> None:
        seen: set[str] = set()
        gallery: list[str] = []

        # Pull every "advertImageList"-shaped node we can find. Keys we care about
        # vary by category: advertImage, imageList, photos, attachmentImages, etc.
        for key in ("advertImageList", "imageList", "photos", "advertImages", "attachments"):
            buckets: list[Any] = []
            _walk(data, key, buckets)
            for il in buckets:
                if isinstance(il, dict):
                    items = (
                        il.get("advertImage") or il.get("imageList")
                        or il.get("attachment") or il.get("photos")
                        or il.get("items") or []
                    )
                elif isinstance(il, list):
                    items = il
                else:
                    continue
                for item in items:
                    if not isinstance(item, dict):
                        # Some lists are just URL strings.
                        if isinstance(item, str):
                            self._add_url(item, base_url, seen, gallery)
                        continue
                    for k in (
                        "referenceImageUrl", "mainImageUrl", "url",
                        "fullSizeUrl", "originalUrl", "src",
                    ):
                        v = item.get(k)
                        if isinstance(v, str):
                            self._add_url(v, base_url, seen, gallery)
                            break

        # If structured extraction produced little, walk the whole state for any
        # URL hosted on a willhaben image CDN.
        if len(gallery) < 8:
            self._collect_image_urls(data, gallery, seen)

        if gallery:
            result.image_urls = gallery[:50]

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

    def _extract_willhaben_address(self, data: Any, result: ImporterResult) -> None:
        """Augment address from the advert state if JSON-LD didn't fill it.

        Willhaben encodes ad fields as a flat list of `{name, values}` records under
        keys like `attributes`, `attribute`, or `extraValues`. Attribute names vary by
        category (real estate, motor, jobs) so we collect every name/value pair we
        can reach and look them up by a generous list of synonyms.
        """
        attrs = self._collect_willhaben_attrs(data)
        if not attrs:
            return

        def first(*keys: str) -> str | None:
            for k in keys:
                v = attrs.get(k)
                if v:
                    return v
            return None

        street = first(
            "ADDRESS", "ADDRESS_2", "STREET", "STREET_NAME",
            "ESTATE_PREMIUM_HOUSE_NUMBER", "OBJECT_ADDRESS",
            "ADDRESS_LINE", "REAL_ESTATE_OBJECT_ADDRESS",
        )
        postal = first(
            "POSTCODE", "POST_CODE", "ZIP_CODE", "ZIP",
            "POSTAL_CODE", "PLZ",
        )
        city = first(
            "LOCATION", "CITY", "TOWN", "ORT",
            "DISTRICT_OF_VIENNA",
        )
        state = first("STATE", "BUNDESLAND", "FEDERAL_STATE")
        district = first(
            "DISTRICT", "DISTRICT_LEVEL_1", "DISTRICT_LEVEL_2",
            "BEZIRK", "STADTTEIL",
        )

        if not result.fields.get("postal_code") and postal:
            result.fields["postal_code"] = postal
        if not result.fields.get("city") and city:
            result.fields["city"] = city

        if not result.fields.get("address"):
            line2_bits = [p for p in (postal, city) if p]
            line2 = " ".join(line2_bits)
            pieces = [p for p in (street, line2, district or state) if p]
            if pieces:
                result.fields["address"] = ", ".join(pieces)[:500]

    def _collect_willhaben_attrs(self, data: Any) -> dict[str, str]:
        """Walk every dict and harvest {name: value} records (multiple shapes)."""
        out: dict[str, str] = {}

        def visit(node: Any) -> None:
            if isinstance(node, dict):
                # Shape A: {"name": "POSTCODE", "values": ["1210"]}
                name = node.get("name")
                if isinstance(name, str) and name.isupper():
                    values = node.get("values") or node.get("value")
                    if isinstance(values, list) and values:
                        v = values[0]
                        if isinstance(v, (str, int)):
                            out.setdefault(name, str(v))
                    elif isinstance(values, (str, int)):
                        out.setdefault(name, str(values))
                # Shape B: {"key": "POSTCODE", "value": "1210"}
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
