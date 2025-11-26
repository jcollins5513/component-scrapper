"""Capture screenshots of component previews."""

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError
import logging
import os
from typing import List, Optional

logger = logging.getLogger(__name__)


def capture_screenshot(
    page: Page,
    output_path: str,
    selectors: Optional[List[str]] = None,
    allow_full_page_fallback: bool = True,
) -> bool:
    """
    Capture a screenshot of the component preview.
    
    Args:
        page: Playwright page object
        output_path: Full path where screenshot should be saved
        selectors: Optional ordered list of selectors to try
        allow_full_page_fallback: Whether to capture the whole page if no selector succeeds
        
    Returns:
        True if successful, False otherwise
    """
    try:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        page.wait_for_load_state('networkidle', timeout=30000)
        page.wait_for_timeout(1000)
        
        selector_list = selectors or [
            '[data-preview]',
            '.preview',
            '[class*="preview"]',
            '[class*="example"]',
            '[class*="demo"]',
            'main',
            'article',
        ]
        
        for selector in selector_list:
            try:
                element = page.locator(selector).first
                if element.count() == 0:
                    continue
                element.scroll_into_view_if_needed(timeout=3000)
                element.wait_for(state='visible', timeout=5000)
                element.screenshot(path=output_path, timeout=15000)
                logger.info(f"Screenshot captured using selector '{selector}' at {output_path}")
                return True
            except Exception:
                continue
        
        if allow_full_page_fallback:
            page.screenshot(path=output_path, full_page=True, timeout=15000)
            logger.info(f"Full page screenshot captured at {output_path}")
            return True
        return False
        
    except PlaywrightTimeoutError:
        logger.error(f"Timeout while capturing screenshot for {output_path}")
        return False
    except Exception as e:
        logger.error(f"Error capturing screenshot: {str(e)}")
        return False

