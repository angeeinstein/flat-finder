"""Importer base class."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ImporterResult:
    fields: dict = field(default_factory=dict)
    image_urls: list[str] = field(default_factory=list)
    text_snapshot: str | None = None
    platform: str | None = None
    external_id: str | None = None
    canonical_url: str | None = None


class ImporterBase(ABC):
    name: str = "abstract"

    @abstractmethod
    def can_handle(self, url: str) -> bool:
        """Return True if this importer should be used for the given URL."""

    @abstractmethod
    def extract(self, url: str, html: str, response) -> ImporterResult:
        """Extract structured data from a fetched page."""
