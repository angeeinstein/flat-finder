"""Importer registry."""
from __future__ import annotations

from app.services.importer.base import ImporterBase
from app.services.importer.generic import GenericImporter
from app.services.importer.immoscout24 import ImmoScout24Importer
from app.services.importer.immowelt import ImmoweltImporter
from app.services.importer.willhaben import WillhabenImporter


_REGISTRY: list[ImporterBase] = [
    WillhabenImporter(),
    ImmoScout24Importer(),
    ImmoweltImporter(),
    GenericImporter(),  # always last (fallback)
]


def get_importer_for(url: str) -> ImporterBase:
    for imp in _REGISTRY:
        if imp.can_handle(url):
            return imp
    return _REGISTRY[-1]
