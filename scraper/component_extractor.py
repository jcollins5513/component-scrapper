"""Extract component metadata from individual component pages."""

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError
from bs4 import BeautifulSoup
import logging
import re
from typing import Dict, List

logger = logging.getLogger(__name__)


BACKGROUND_KEYWORDS = [
    "background",
    "glow",
    "aurora",
    "meteor",
    "spotlight",
    "grid",
    "beam",
    "vortex",
    "lamp",
    "stars",
]

CARD_KEYWORDS = [
    "card",
    "stack",
    "spotlight",
    "wobble",
    "glare",
    "focus",
    "testimonial",
    "pricing",
]

HERO_KEYWORDS = [
    "hero",
    "feature",
    "section",
    "headline",
]

BUTTON_KEYWORDS = [
    "button",
    "cta",
    "call-to-action",
    "floating-dock",
]

FORM_KEYWORDS = [
    "form",
    "input",
    "signup",
    "upload",
    "placeholder",
]

NAV_KEYWORDS = [
    "navbar",
    "navigation",
    "tabs",
    "sidebar",
    "menu",
]

POINTER_KEYWORDS = [
    "hover",
    "pointer",
    "cursor",
]

SCROLL_KEYWORDS = [
    "scroll",
    "parallax",
    "sticky",
    "macbook",
]


def _normalize_slug(url: str) -> str:
    return url.rstrip('/').split('/')[-1]


def _infer_profile(slug: str, tags: List[str], description: str) -> Dict[str, object]:
    text = " ".join(filter(None, [slug.replace("-", " "), " ".join(tags or []), description or ""])).lower()
    profile = {
        "type": "widget",
        "subtype": "",
        "layout_role": "content-block",
        "recommended_slots": ["generic"],
        "interaction_profile": "static",
        "preferred_size": "flexible",
        "z_index_role": "content",
        "data_requirements": [],
    }

    def any_keyword(keywords):
        return any(keyword in text for keyword in keywords)

    if any_keyword(BACKGROUND_KEYWORDS):
        profile.update({
            "type": "background",
            "layout_role": "background-layer",
            "recommended_slots": ["hero.background", "section.background"],
            "interaction_profile": "animated",
            "preferred_size": "full-bleed",
            "z_index_role": "background",
        })
    elif any_keyword(HERO_KEYWORDS):
        profile.update({
            "type": "hero",
            "layout_role": "section",
            "recommended_slots": ["hero.primary", "section.lead"],
            "preferred_size": "full-width",
        })
    elif any_keyword(CARD_KEYWORDS):
        profile.update({
            "type": "card",
            "layout_role": "inline-block",
            "recommended_slots": ["grid.item", "section.content"],
            "preferred_size": "auto-height",
            "data_requirements": [{"name": "items", "fields": ["title", "description", "media"], "type": "array"}],
        })
    elif any_keyword(BUTTON_KEYWORDS):
        profile.update({
            "type": "button",
            "layout_role": "inline",
            "recommended_slots": ["cta.primary", "cta.secondary"],
            "preferred_size": "inline",
            "interaction_profile": "interactive",
        })
    elif any_keyword(FORM_KEYWORDS):
        profile.update({
            "type": "form",
            "layout_role": "container",
            "recommended_slots": ["auth", "lead-capture"],
            "preferred_size": "content-width",
            "interaction_profile": "input",
        })
    elif any_keyword(NAV_KEYWORDS):
        profile.update({
            "type": "navigation",
            "layout_role": "sticky",
            "recommended_slots": ["header", "sidebar"],
            "preferred_size": "full-width",
        })

    if any_keyword(POINTER_KEYWORDS):
        profile["interaction_profile"] = "pointer-reactive"
    elif any_keyword(SCROLL_KEYWORDS):
        profile["interaction_profile"] = "scroll-reactive"

    return profile


def _infer_usage_notes(description: str, profile_type: str) -> str:
    if description:
        return description
    fallback = {
        "background": "Use as a decorative animated background layer for hero or section rows.",
        "hero": "Primary hero section with bold copy and supporting visuals.",
        "card": "Card layout suitable for feature highlights, pricing, or testimonials.",
        "button": "Call-to-action button with advanced hover/animation effects.",
        "form": "Interactive form/input pattern for lead capture or onboarding.",
        "navigation": "Navigation component for headers, sidebars, or floating docks.",
    }
    return fallback.get(profile_type, "Reusable UI component for marketing-style layouts.")


def _infer_theme_requirements(description: str, tags: List[str]) -> List[str]:
    text = " ".join(filter(None, [description or "", " ".join(tags or [])])).lower()
    requirements = []
    if "dark" in text:
        requirements.append("dark-mode-friendly")
    if "light" in text:
        requirements.append("light-mode-friendly")
    if "tailwind" in text:
        requirements.append("tailwind-classes")
    return requirements


def _infer_domain_tags(description: str) -> List[str]:
    text = (description or "").lower()
    tags = []
    if "saas" in text or "startup" in text:
        tags.append("saas")
    if "portfolio" in text:
        tags.append("portfolio")
    if "ecommerce" in text or "shop" in text:
        tags.append("ecommerce")
    if "agency" in text or "marketing" in text:
        tags.append("marketing")
    return tags


def extract_metadata(page: Page, component_url: str) -> dict:
    """
    Extract metadata from a component page.
    
    Args:
        page: Playwright page object
        component_url: URL of the component page
        
    Returns:
        Dictionary with component metadata
    """
    metadata = {
        'name': '',
        'slug': _normalize_slug(component_url),
        'description': '',
        'props': [],
        'category': '',
        'tags': [],
        'installation': '',
        'url': component_url,
        'type': 'widget',
        'subtype': '',
        'layout_role': 'content-block',
        'recommended_slots': ['generic'],
        'interaction_profile': 'static',
        'preferred_size': 'flexible',
        'z_index_role': 'content',
        'usage_notes': '',
        'theme_requirements': [],
        'data_requirements': [],
        'domain_tags': [],
        'imports': [],
        'dependencies': [],
        'client_only': False,
    }
    
    try:
        logger.info(f"Extracting metadata from {component_url}")
        page.goto(component_url, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(2000)  # Wait for dynamic content
        
        content = page.content()
        soup = BeautifulSoup(content, 'html.parser')
        
        # Extract component name (usually in h1 or title)
        h1 = soup.find('h1')
        if h1:
            metadata['name'] = h1.get_text(strip=True)
        else:
            # Fallback to title tag
            title = soup.find('title')
            if title:
                title_text = title.get_text(strip=True)
                # Remove common suffixes
                metadata['name'] = title_text.replace(' - Aceternity UI', '').strip()
        
        # Extract description (usually in first paragraph or meta description)
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            metadata['description'] = meta_desc.get('content')
        else:
            # Look for description paragraphs
            desc_paragraphs = soup.find_all('p', limit=3)
            for p in desc_paragraphs:
                text = p.get_text(strip=True)
                if len(text) > 50:  # Likely a description
                    metadata['description'] = text
                    break
        
        # Extract props table if available
        props_table = soup.find('table')
        if props_table:
            headers = []
            header_row = props_table.find('tr')
            if header_row:
                headers = [th.get_text(strip=True) for th in header_row.find_all(['th', 'td'])]
            
            rows = props_table.find_all('tr')[1:]  # Skip header
            for row in rows:
                cells = row.find_all(['td', 'th'])
                if len(cells) >= 2:
                    prop_data = {}
                    for i, cell in enumerate(cells):
                        if i < len(headers):
                            prop_data[headers[i]] = cell.get_text(strip=True)
                    if prop_data:
                        metadata['props'].append(prop_data)
        
        # Extract category/tags (look for tags, badges, or category indicators)
        tags_elements = soup.find_all(['span', 'div', 'a'], 
                                     class_=re.compile(r'tag|badge|category', re.I))
        for tag_elem in tags_elements:
            tag_text = tag_elem.get_text(strip=True)
            if tag_text and len(tag_text) < 30:  # Reasonable tag length
                metadata['tags'].append(tag_text)
        
        # Extract installation instructions
        # Look for code blocks with installation commands
        code_blocks = soup.find_all(['pre', 'code'])
        for code_block in code_blocks:
            code_text = code_block.get_text(strip=True)
            if 'install' in code_text.lower() or 'npx' in code_text.lower() or 'npm' in code_text.lower():
                metadata['installation'] = code_text
                break
        
        # Try to find category from navigation or breadcrumbs
        breadcrumbs = soup.find_all(['nav', 'ol', 'ul'], class_=re.compile(r'breadcrumb|nav', re.I))
        for breadcrumb in breadcrumbs:
            links = breadcrumb.find_all('a')
            for link in links:
                href = link.get('href', '')
                if '/components/' in href and href != component_url:
                    category = href.split('/components/')[-1].split('/')[0]
                    if category and category != metadata['name']:
                        metadata['category'] = category
                        break
        
        profile = _infer_profile(metadata['slug'], metadata['tags'], metadata['description'])
        metadata.update({
            'type': profile['type'],
            'subtype': profile.get('subtype', ''),
            'layout_role': profile['layout_role'],
            'recommended_slots': profile['recommended_slots'],
            'interaction_profile': profile['interaction_profile'],
            'preferred_size': profile['preferred_size'],
            'z_index_role': profile['z_index_role'],
            'data_requirements': profile['data_requirements'],
        })
        metadata['usage_notes'] = _infer_usage_notes(metadata['description'], metadata['type'])
        metadata['theme_requirements'] = _infer_theme_requirements(metadata['description'], metadata['tags'])
        metadata['domain_tags'] = _infer_domain_tags(metadata['description'])

        logger.info(f"Extracted metadata for {metadata['name']}")
        return metadata
        
    except PlaywrightTimeoutError:
        logger.error(f"Timeout while loading {component_url}")
        return metadata
    except Exception as e:
        logger.error(f"Error extracting metadata from {component_url}: {str(e)}")
        return metadata

