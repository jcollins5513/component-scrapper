"""Source adapter registry for component scraping."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence

from playwright.sync_api import Page


MetadataExtractor = Callable[[Page, Dict], Dict]
CodeExtractor = Callable[[Page, Dict], Dict]
Finder = Callable[[Optional[Page], Optional[int]], List[Dict]]
LayoutAnalyzer = Callable[[Page, Optional[str], Optional[str]], Dict]


@dataclass
class SourceAdapter:
    """Encapsulates behaviour for a specific component source."""

    name: str
    finder: Finder
    metadata_extractor: MetadataExtractor
    code_extractor: CodeExtractor
    preview_selectors: Optional[Sequence[str]] = None
    code_selectors: Optional[Sequence[str]] = None
    layout_analyzer: Optional[LayoutAnalyzer] = None


class UnknownSourceError(ValueError):
    """Raised when an unsupported source is requested."""


def _lazy_import_aceternity() -> SourceAdapter:
    from . import aceternity

    return aceternity.get_adapter()


def _lazy_import_aura() -> SourceAdapter:
    from . import aura

    return aura.get_adapter()


def _lazy_import_magic() -> SourceAdapter:
    from . import magic

    return magic.get_adapter()


ADAPTER_LOADERS = {
    "aceternity": _lazy_import_aceternity,
    "aura": _lazy_import_aura,
    "magic": _lazy_import_magic,
}


def get_adapter(source: str) -> SourceAdapter:
    """Return a SourceAdapter for the given source name."""

    normalized = (source or "aceternity").lower()
    loader = ADAPTER_LOADERS.get(normalized)
    if not loader:
        raise UnknownSourceError(f"Unsupported source '{source}'. Expected one of {list(ADAPTER_LOADERS)}.")
    return loader()






