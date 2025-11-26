"""Extract code examples from component pages."""

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError
from bs4 import BeautifulSoup
import logging
import re
from typing import Any, List, Dict

logger = logging.getLogger(__name__)

CODE_TAB_SELECTORS = [
    'button[id*="trigger-code"]',
    '[role="tab"][id*="trigger-code"]',
    'button:has-text("Code")',
    'a:has-text("Code")',
    '[data-state="inactive"][role="tab"]:has-text("Code")',
]

CODE_BLOCK_SELECTORS = [
    '[role="tabpanel"][data-state="active"] pre',
    '[data-state="active"] pre',
    '[data-state="active"] [data-language]',
    'pre code',
]


def _flatten_strings(data: Any, collector: List[str]) -> None:
    """Recursively gather string entries from nested Next.js flight data."""
    if isinstance(data, str):
        collector.append(data)
    elif isinstance(data, list) or isinstance(data, tuple):
        for item in data:
            _flatten_strings(item, collector)


def _extract_from_next_f(page: Page) -> dict:
    """Attempt to extract code snippets from Next.js flight data."""
    try:
        flight_data = page.evaluate("self.__next_f || []")
    except Exception as exc:
        logger.debug(f"Unable to read __next_f: {exc}")
        return {}

    strings: List[str] = []
    _flatten_strings(flight_data, strings)

    # Heuristic: choose the longest string that looks like TS/JS component code
    candidates = []
    for text in strings:
        if len(text) < 200:
            continue
        lowered = text.lower()
        if any(keyword in lowered for keyword in ["export const", "function ", "use client", "import react"]):
            candidates.append(text.strip())

    if not candidates:
        return {}

    candidates.sort(key=len)  # sort ascending to easily find reasonable sizes
    reasonable = [text for text in candidates if len(text) <= 20000]
    target_list = reasonable if reasonable else candidates

    if not target_list:
        return {}

    # Choose the longest snippet within the reasonable bucket to retain full component code
    code_text = max(target_list, key=len)
    language = "tsx" if "type " in code_text or ": React" in code_text else "jsx"

    logger.info("Extracted code from __next_f payload")
    return {"code": code_text, "language": language}


def _click_code_tab(page: Page) -> bool:
    for selector in CODE_TAB_SELECTORS:
        try:
            locator = page.locator(selector).first
            if locator.count() > 0:
                locator.scroll_into_view_if_needed(timeout=2000)
                locator.click()
                page.wait_for_timeout(600)
                return True
        except Exception:
            continue
    return False


def _collect_pre_texts(page: Page) -> List[str]:
    try:
        return page.eval_on_selector_all(
            'pre',
            "els => els.map(el => el.innerText || el.textContent || '')"
        )
    except Exception:
        return []


def _detect_imports(code_text: str) -> Dict[str, List[str]]:
    import_lines = re.findall(r'^\s*import\s+.+$', code_text, flags=re.MULTILINE)
    dependencies = []
    for line in import_lines:
        match = re.search(r'from\s+[\'"]([^\'"]+)[\'"]', line)
        if match:
            module = match.group(1)
            if module.startswith('.'):
                continue
            dependencies.append(module)
    return {
        "imports": import_lines,
        "dependencies": sorted(set(dependencies)),
    }


def extract_code(page: Page) -> dict:
    """
    Extract code examples from a component page.
    
    Args:
        page: Playwright page object
        
    Returns:
        Dictionary with 'code' (code content) and 'language' (detected language)
    """
    result = {
        'code': '',
        'language': 'tsx',  # Default to TSX for React components
        'client_only': False,
        'imports': [],
        'dependencies': [],
        'activated_code_tab': False,
    }
    
    try:
        # Wait for page to load
        page.wait_for_load_state('networkidle', timeout=30000)
        page.wait_for_timeout(1500)

        activated = _click_code_tab(page)
        result['activated_code_tab'] = activated

        pre_texts = _collect_pre_texts(page)
        candidate_texts = []
        for text in pre_texts:
            if len(text) < 100:
                continue
            lowered = text.lower()
            if any(keyword in lowered for keyword in ['export ', 'function ', 'const ', 'use client', '<']):
                candidate_texts.append(text.strip())

        if candidate_texts:
            candidate_texts.sort(key=len, reverse=True)
            result['code'] = candidate_texts[0]
        else:
            # Fall back to BeautifulSoup on full HTML
            content = page.content()
            soup = BeautifulSoup(content, 'html.parser')
            pre_tags = soup.find_all('pre')
            for pre in pre_tags:
                code_elem = pre.find('code')
                if code_elem:
                    code_text = code_elem.get_text()
                    if len(code_text) > 100 and any(keyword in code_text for keyword in ['export', 'function', 'const', '<', 'import']):
                        result['code'] = code_text
                        break

        # Try to find code in script tags with type="text/plain" or similar
        if not result['code']:
            content = page.content()
            soup = BeautifulSoup(content, 'html.parser')
            script_tags = soup.find_all('script', type=re.compile(r'text/(plain|code|typescript|javascript)', re.I))
            for script in script_tags:
                code_text = script.get_text()
                if len(code_text) > 100:
                    result['code'] = code_text
                    break
        
        # Detect language from code content if not already detected
        if result['code']:
            code_lower = result['code'].lower()
            if result['language'] == 'tsx':
                if '.tsx' in code_lower or 'tsx' in code_lower or 'typescript' in code_lower:
                    result['language'] = 'tsx'
                elif '.jsx' in code_lower or 'jsx' in code_lower:
                    result['language'] = 'jsx'
                elif '.ts' in code_lower:
                    result['language'] = 'ts'
                elif '.js' in code_lower:
                    result['language'] = 'js'
            first_line = result['code'].splitlines()[0].lower() if result['code'].splitlines() else ""
            result['client_only'] = '"use client"' in result['code'].lower() or 'use client' in first_line
            import_info = _detect_imports(result['code'])
            result['imports'] = import_info['imports']
            result['dependencies'] = import_info['dependencies']
        else:
            # Fallback: check Next.js flight data for component code
            next_f_code = _extract_from_next_f(page)
            if next_f_code:
                result.update(next_f_code)
                result.setdefault('imports', [])
                result.setdefault('dependencies', [])
                result['client_only'] = '"use client"' in result['code'][:50].lower()
        
        if result['code']:
            logger.info(f"Extracted code ({result['language']}) with {len(result['code'])} characters")
        else:
            logger.warning("No code found on page")
        
        return result
        
    except PlaywrightTimeoutError:
        logger.error("Timeout while extracting code")
        return result
    except Exception as e:
        logger.error(f"Error extracting code: {str(e)}")
        return result

