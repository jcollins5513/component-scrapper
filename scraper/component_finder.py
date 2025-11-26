"""Discover non-pro components from Aceternity UI."""

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError
from bs4 import BeautifulSoup
import logging
import re
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


def _normalize_url(href: str, base_url: str) -> Optional[str]:
    """Return fully qualified URL for component links."""
    if not href:
        return None
    if href.startswith('http'):
        return href
    if href.startswith('/'):
        return f"{base_url}{href}"
    # Skip hash links
    if href.startswith('#'):
        return None
    return f"{base_url}/{href}"


def _looks_like_component(href: str) -> bool:
    """Quick check if href points to a component detail page."""
    if not href:
        return False
    href_lower = href.lower()
    if 'pro' in href_lower:
        return False
    return '/components/' in href_lower and not href_lower.rstrip('/').endswith('/components')


def _scroll_page(page: Page, steps: int = 8, delay_ms: int = 400):
    """Scroll the listing page to trigger lazy loading."""
    for _ in range(steps):
        page.mouse.wheel(0, 1600)
        page.wait_for_timeout(delay_ms)


def find_components(page: Page, base_url: str = "https://ui.aceternity.com") -> List[Dict[str, str]]:
    """
    Find all non-pro component URLs from the Aceternity UI components page.
    
    Args:
        page: Playwright page object
        base_url: Base URL for Aceternity UI
        
    Returns:
        List of dictionaries with 'name' and 'url' keys for each non-pro component
    """
    components = []
    seen_urls = set()
    
    try:
        components_url = f"{base_url}/components"
        logger.info(f"Navigating to {components_url}")
        page.goto(components_url, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(2000)
        
        # Scroll to ensure all component cards render
        _scroll_page(page)
        page.wait_for_timeout(500)
        
        # Use the live DOM (more reliable than static HTML snapshot) to find links
        try:
            page.wait_for_selector('a[href*="/components/"]', timeout=5000)
        except PlaywrightTimeoutError:
            logger.warning("No component links became visible via selector search")
        
        dom_links = page.eval_on_selector_all(
            'a[href*="/components/"]',
            """els => els.map(el => ({
                href: el.getAttribute('href'),
                text: (el.innerText || el.textContent || '').trim()
            }))"""
        )
        
        logger.info(f"Found {len(dom_links)} raw component-like links via DOM scan")
        
        for link_info in dom_links:
            href = link_info.get('href') or ''
            text = link_info.get('text', '')
            
            if not _looks_like_component(href):
                continue
            
            full_url = _normalize_url(href, base_url)
            if not full_url or full_url in seen_urls:
                continue
            
            # Filter out pro/premium by link text
            text_lower = text.lower()
            if 'pro' in text_lower and any(word in text_lower for word in ['pro', 'premium', 'upgrade', 'buy']):
                continue
            
            component_name = full_url.rstrip('/').split('/')[-1]
            components.append({'name': component_name, 'url': full_url})
            seen_urls.add(full_url)
            logger.info(f"Found component via DOM: {component_name} -> {full_url}")
        
        # Fallback: parse HTML snapshot if DOM scan was empty
        if not components:
            content = page.content()
            soup = BeautifulSoup(content, 'html.parser')
            all_links = soup.find_all('a', href=True)
            
            for link in all_links:
                href = link.get('href', '')
                if not _looks_like_component(href):
                    continue
                
                full_url = _normalize_url(href, base_url)
                if not full_url or full_url in seen_urls:
                    continue
                
                link_text = link.get_text(strip=True).lower()
                if 'pro' in link_text and any(word in link_text for word in ['pro', 'premium', 'upgrade', 'buy']):
                    continue
                
                components.append({
                    'name': full_url.rstrip('/').split('/')[-1],
                    'url': full_url
                })
                seen_urls.add(full_url)
                logger.info(f"Found component via fallback HTML: {full_url}")
        
        logger.info(f"Total non-pro components found: {len(components)}")
        return components
        
    except PlaywrightTimeoutError:
        logger.error("Timeout while loading components page")
        return []
    except Exception as e:
        logger.error(f"Error finding components: {str(e)}")
        return []

