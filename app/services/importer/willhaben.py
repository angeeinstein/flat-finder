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
        seen = set(result.image_urls)
        gallery: list[str] = []

        # advertImageList -> { advertImage: [ { mainImageUrl, referenceImageUrl } ] }
        image_lists: list[Any] = []
        _walk(data, "advertImageList", image_lists)
        for il in image_lists:
            if isinstance(il, dict):
                items = il.get("advertImage") or il.get("imageList") or []
            elif isinstance(il, list):
                items = il
            else:
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                # Prefer the largest variant
                for k in ("referenceImageUrl", "mainImageUrl", "thumbnailImageUrl", "url"):
                    v = item.get(k)
                    if isinstance(v, str):
                        absolute = urljoin(base_url, v)
                        if absolute in seen:
                            break
                        if not _looks_like_property_image(absolute):
                            break
                        seen.add(absolute)
                        gallery.append(absolute)
                        break

        # Fallback: walk for any URLs hosted on willhaben image CDNs
        if not gallery:
            urls: list[str] = []
            self._collect_image_urls(data, urls, seen)
            gallery.extend(urls)

        if gallery:
            # Put the willhaben gallery first, then any extras the generic picked up
            keep = [u for u in result.image_urls if u not in set(gallery)]
            result.image_urls = (gallery + keep)[:50]

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
        """Augment address from the advert state if JSON-LD didn't fill it."""
        # Willhaben puts an "attributes" array of {name, values} entries.
        attrs_lists: list[Any] = []
        _walk(data, "attributes", attrs_lists)
        attrs: dict[str, str] = {}
        for al in attrs_lists:
            if isinstance(al, dict):
                items = al.get("attribute") or al.get("attributes") or []
            elif isinstance(al, list):
                items = al
            else:
                continue
            for it in items:
                if not isinstance(it, dict):
                    continue
                name = it.get("name") or it.get("key")
                values = it.get("values") or it.get("value")
                if not name:
                    continue
                if isinstance(values, list) and values:
                    attrs[name] = str(values[0])
                elif isinstance(values, str):
                    attrs[name] = values

        # Common willhaben address attribute names (slightly different across types)
        street = attrs.get("ADDRESS") or attrs.get("ADDRESS_2") or attrs.get("STREET")
        postal = attrs.get("POSTCODE") or attrs.get("ZIP_CODE") or attrs.get("ZIP")
        city = attrs.get("LOCATION") or attrs.get("CITY") or attrs.get("STATE")
        district = attrs.get("DISTRICT") or attrs.get("DISTRICT_LEVEL_1")

        if street and not result.fields.get("address"):
            pieces = [p for p in (street, " ".join(p for p in (postal, city) if p), district) if p]
            result.fields["address"] = ", ".join(pieces)[:500]
        if postal and not result.fields.get("postal_code"):
            result.fields["postal_code"] = postal
        if city and not result.fields.get("city"):
            result.fields["city"] = city
