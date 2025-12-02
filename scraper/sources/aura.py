"""Adapter for Aura Build templates."""

from __future__ import annotations

import math
from typing import Dict, List, Optional

import requests
from playwright.sync_api import Page

from . import SourceAdapter

SUPABASE_URL = "https://hoirqrkdgbmvpwutwuwj.supabase.co/rest/v1/shared_code"
SUPABASE_HEADERS = {
    "apikey": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImhvaXJxcmtkZ2JtdnB3dXR3dXdqIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDM2Nzc2NTAsImV4cCI6MjA1OTI1MzY1MH0._UsCSHsTELn7m54tOhX3ySm67WEhcyHAPbuxEQZsl3c",
    "Authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImhvaXJxcmtkZ2JtdnB3dXR3dXdqIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDM2Nzc2NTAsImV4cCI6MjA1OTI1MzY1MH0._UsCSHsTELn7m54tOhX3ySm67WEhcyHAPbuxEQZsl3c",
    "Accept-Profile": "public",
}
DEFAULT_BATCH_SIZE = 20


def _fetch_batch(offset: int, limit: int) -> List[Dict]:
    params = {
        "select": "*,profiles:user_id(id,full_name,avatar_url,slug,is_featured)",
        "or": "(private.is.null,private.eq.false)",
        "featured": "eq.true",
        "views": "gte.50",
        "order": "created_at.desc",
        "offset": str(offset),
        "limit": str(limit),
    }
    response = requests.get(SUPABASE_URL, params=params, headers=SUPABASE_HEADERS, timeout=30)
    response.raise_for_status()
    return response.json()


def _find_components(_: Optional[Page], limit: Optional[int] = None) -> List[Dict]:
    """Fetch template metadata from Supabase."""

    results: List[Dict] = []
    batch_size = DEFAULT_BATCH_SIZE
    target = limit or math.inf
    offset = 0

    while len(results) < target:
        batch = _fetch_batch(offset, batch_size)
        if not batch:
            break
        for entry in batch:
            slug = entry.get("slug") or str(entry.get("id"))
            component = {
                "name": entry.get("title") or slug,
                "slug": slug,
                "url": f"https://www.aura.build/share/{slug}",
                "raw": entry,
                "preview_image_url": entry.get("image_url"),
            }
            results.append(component)
            if len(results) >= target:
                break
        offset += batch_size

    return results[: target if math.isfinite(target) else None]


def _extract_metadata(_: Page, component: Dict) -> Dict:
    data = component.get("raw", {})
    slug = component.get("slug")
    profile = data.get("profiles") or {}
    description = data.get("description") or ""
    tags = data.get("tags") or []
    category = data.get("category") or "Web"

    metadata = {
        "name": data.get("title") or slug,
        "slug": slug,
        "description": description,
        "tags": tags,
        "category": category,
        "installation": "",
        "url": component.get("url"),
        "type": "template",
        "layout_role": "section",
        "recommended_slots": ["landing.hero", "landing.section", "gallery"],
        "interaction_profile": "static",
        "preferred_size": "full-width",
        "z_index_role": "content",
        "usage_notes": description or "Aura Build template scraped from browse/components.",
        "theme_requirements": ["tailwindcss"],
        "data_requirements": [],
        "domain_tags": _derive_domain_tags(tags, description),
        "source": "aura",
        "author": {
            "name": profile.get("full_name"),
            "slug": profile.get("slug"),
            "avatar_url": profile.get("avatar_url"),
            "featured": profile.get("is_featured"),
        },
        "preview_image_url": component.get("preview_image_url"),
        "aura": {
            "id": data.get("id"),
            "views": data.get("views"),
            "forks": data.get("forks"),
            "premium": data.get("premium"),
        },
    }
    return metadata


def _derive_domain_tags(tags: List[str], description: str) -> List[str]:
    text = " ".join(tags + [description]).lower()
    domains = []
    if any(token in text for token in ["saas", "startup", "app"]):
        domains.append("saas")
    if "portfolio" in text:
        domains.append("portfolio")
    if any(token in text for token in ["ecommerce", "shop", "store", "marketplace"]):
        domains.append("ecommerce")
    if any(token in text for token in ["agency", "marketing", "studio"]):
        domains.append("marketing")
    return domains


def _extract_code(_: Page, component: Dict) -> Dict:
    data = component.get("raw", {})
    code_text = data.get("code") or ""
    dependencies = []
    lower = code_text.lower()
    if "cdn.tailwindcss.com" in lower:
        dependencies.append("tailwindcss")
    if "framer-motion" in lower:
        dependencies.append("framer-motion")
    if "three.js" in lower or "threejs" in lower:
        dependencies.append("three")

    return {
        "code": code_text,
        "language": "html",
        "client_only": True,
        "imports": [],
        "dependencies": dependencies,
    }


def get_adapter() -> SourceAdapter:
    # Aura detail pages render previews in an iframe, so fall back to full-page captures.
    return SourceAdapter(
        name="aura",
        finder=_find_components,
        metadata_extractor=_extract_metadata,
        code_extractor=_extract_code,
        preview_selectors=None,
        code_selectors=None,
    )






