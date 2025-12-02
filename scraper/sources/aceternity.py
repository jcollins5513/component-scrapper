"""Adapter for the Aceternity UI component source."""

from __future__ import annotations

from typing import Dict, List, Optional

from playwright.sync_api import Page

from .. import code_extractor, component_extractor, component_finder
from . import SourceAdapter


def _find_components(page: Optional[Page], _: Optional[int] = None) -> List[Dict]:
    """Reuse the existing component finder logic."""

    if page is None:
        raise ValueError("Aceternity finder requires an active Playwright page.")
    return component_finder.find_components(page)


def _extract_metadata(page: Page, component: Dict) -> Dict:
    return component_extractor.extract_metadata(page, component["url"])


def _extract_code(page: Page, _: Dict) -> Dict:
    return code_extractor.extract_code(page)


def get_adapter() -> SourceAdapter:
    return SourceAdapter(
        name="aceternity",
        finder=_find_components,
        metadata_extractor=_extract_metadata,
        code_extractor=_extract_code,
        preview_selectors=None,
        code_selectors=None,
    )






