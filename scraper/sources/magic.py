"""Adapter for Magic UI documentation components."""

from __future__ import annotations

import re
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import Page

from .. import code_extractor
from . import SourceAdapter

DOCS_INDEX = "https://magicui.design/docs/components"


def _fetch_index_links() -> List[Dict]:
    response = requests.get(DOCS_INDEX, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    components: List[Dict] = []
    for anchor in soup.select('a[href^="/docs/components/"]'):
        href = anchor.get("href")
        if not href:
            continue
        slug = href.rstrip("/").split("/")[-1]
        name = anchor.get_text(strip=True) or slug.replace("-", " ").title()
        components.append(
            {
                "name": name,
                "slug": slug,
                "url": f"https://magicui.design{href}",
                "category": _infer_category_from_href(href),
            }
        )
    # Deduplicate while preserving order
    seen = set()
    unique: List[Dict] = []
    for item in components:
        if item["slug"] in seen:
            continue
        seen.add(item["slug"])
        unique.append(item)
    return unique


def _infer_category_from_href(href: str) -> str:
    if "background" in href:
        return "background"
    if "button" in href:
        return "button"
    if "text" in href:
        return "text"
    if "animation" in href or "animated" in href:
        return "animation"
    if "device" in href or "iphone" in href or "android" in href or "safari" in href:
        return "device"
    if "mock" in href or "dock" in href or "grid" in href or "bento" in href:
        return "layout"
    return "component"


def _find_components(_: Optional[Page], limit: Optional[int] = None) -> List[Dict]:
    items = _fetch_index_links()
    if limit:
        return items[:limit]
    return items


def _extract_metadata(page: Page, component: Dict) -> Dict:
    page.goto(component["url"], wait_until="networkidle")
    page.wait_for_timeout(1500)
    name = component.get("name") or page.locator("h1").first.inner_text()
    description = page.evaluate(
        """
        () => {
            const heading = document.querySelector('h1');
            if (!heading) return '';
            let el = heading.nextElementSibling;
            while (el) {
                if (el.tagName && el.tagName.toLowerCase() === 'p' && el.textContent.trim().length) {
                    return el.textContent.trim();
                }
                el = el.nextElementSibling;
            }
            return '';
        }
        """
    )
    tags = _extract_tags_from_page(page)
    metadata = {
        "name": name,
        "slug": component.get("slug"),
        "description": description or f"{name} component from Magic UI.",
        "tags": tags,
        "category": component.get("category") or "component",
        "installation": "",
        "url": component.get("url"),
        "type": "component",
        "layout_role": "widget",
        "recommended_slots": ["section.content", "marketing.feature"],
        "interaction_profile": "static",
        "preferred_size": "flexible",
        "z_index_role": "content",
        "usage_notes": description or "Magic UI component.",
        "theme_requirements": ["tailwindcss"],
        "data_requirements": [],
        "domain_tags": [],
        "source": "magic",
    }
    return metadata


def _extract_tags_from_page(page: Page) -> List[str]:
    try:
        chips = page.eval_on_selector_all(
            "[data-slot='label'], .rounded-full.text-xs",
            "els => els.map(el => el.textContent?.trim()).filter(Boolean)"
        )
        if chips:
            return chips
    except Exception:
        pass
    return []


def _extract_code(page: Page, _: Dict) -> Dict:
    # Reuse the generic code extractor to pull from code tabs.
    return code_extractor.extract_code(page)


def get_adapter() -> SourceAdapter:
    code_selectors = [
        "[data-state='active'] pre",
        "pre code",
    ]
    return SourceAdapter(
        name="magic",
        finder=_find_components,
        metadata_extractor=_extract_metadata,
        code_extractor=_extract_code,
        preview_selectors=None,
        code_selectors=code_selectors,
    )

