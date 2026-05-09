"""Willhaben.at apartment listing importer.

Builds on the generic importer's JSON-LD/OpenGraph extraction and adds
Willhaben-specific touches (URL pattern, external ID).
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from app.services.importer.generic import GenericImporter
from app.services.importer.base import ImporterResult


WILLHABEN_HOSTS = ("www.willhaben.at", "willhaben.at")
EXTERNAL_ID_RE = re.compile(r"(?:^|[/\-_])(\d{6,})(?:[/?#]|$)")


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
        return result
