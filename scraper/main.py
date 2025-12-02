"""Main scraper orchestration for multi-source component harvesting."""

import os
import json
import logging
import time
import shutil
from pathlib import Path
from typing import Dict, Optional, Sequence

import requests
from playwright.sync_api import sync_playwright, Page

from .screenshot_capture import capture_screenshot
from .sources import get_adapter, SourceAdapter
from .layout_analyzer import analyze_layout

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('scraper.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

CODE_TAB_SELECTORS = [
    'button[id*="trigger-code"]',
    '[role="tab"][id*="trigger-code"]',
    'button:has-text("Code")',
    'a:has-text("Code")',
    '[data-state="inactive"][role="tab"]:has-text("Code")',
]

CODE_PANEL_SELECTORS = [
    '[role="tabpanel"][data-state="active"] pre',
    '[data-state="active"] pre',
    '[data-state="active"] [data-language]',
    '[data-state="active"] code',
    'pre code',
]


def download_asset(url: Optional[str], destination: Path) -> bool:
    """Download a remote asset to the destination path."""

    if not url:
        return False
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        destination.parent.mkdir(parents=True, exist_ok=True)
        with open(destination, "wb") as handle:
            handle.write(response.content)
        logger.info("Downloaded asset %s -> %s", url, destination)
        return True
    except Exception as exc:
        logger.warning("Failed to download asset %s: %s", url, exc)
        return False


class ComponentScraper:
    """Main scraper class for Aceternity UI components."""
    
    def __init__(
        self,
        output_dir: str = "library",
        base_url: str = "https://ui.aceternity.com",
        delay: float = 2.0,
        browser_executable: Optional[str] = None,
        screenshot_mode: str = "both",
        source: str = "aceternity",
        layout_analysis: bool = True,
    ):
        """
        Initialize the scraper.
        
        Args:
            output_dir: Directory to save scraped components
            base_url: Base URL for Aceternity UI
            delay: Delay in seconds between requests
            browser_executable: Optional path to Chromium/Chrome executable
            screenshot_mode: Which screenshots to capture (preview, code, both)
            layout_analysis: Whether to perform layout analysis (default: True)
        """
        self.source = source
        self.adapter: SourceAdapter = get_adapter(source)
        self.base_output_dir = Path(output_dir)
        self.output_dir = self.base_output_dir / source
        self.components_dir = self.output_dir / "components"
        self.base_url = base_url
        self.delay = delay
        self.browser_executable = browser_executable
        self.screenshot_mode = screenshot_mode if screenshot_mode in {"preview", "code", "both"} else "both"
        self.layout_analysis = layout_analysis
        self.components_index = []
        
        # Create output directories
        self.components_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.output_dir / "index.json"
    
    def sanitize_filename(self, name: str) -> str:
        """Sanitize component name for use as filename."""
        # Remove invalid characters
        name = name.lower().strip()
        name = name.replace(' ', '-')
        name = ''.join(c for c in name if c.isalnum() or c in ('-', '_'))
        return name
    
    def save_component(
        self,
        component_name: str,
        metadata: dict,
        code: dict,
        screenshots: Optional[Dict[str, str]] = None,
        layout: Optional[dict] = None,
    ) -> bool:
        """
        Save component data to library structure.
        
        Args:
            component_name: Name of the component
            metadata: Component metadata dictionary
            code: Code dictionary with 'code' and 'language' keys
            screenshot_path: Path to screenshot file
            
        Returns:
            True if successful, False otherwise
        """
        try:
            sanitized_name = self.sanitize_filename(component_name)
            component_dir = self.components_dir / sanitized_name
            component_dir.mkdir(parents=True, exist_ok=True)
            metadata["source"] = metadata.get("source") or self.source
            
            # Save metadata
            metadata_path = component_dir / "metadata.json"
            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
            
            # Save code
            if code.get('code'):
                code_ext = code.get('language', 'tsx')
                code_path = component_dir / f"code.{code_ext}"
                with open(code_path, 'w', encoding='utf-8') as f:
                    f.write(code['code'])
            
            screenshot_summary = {'preview': False, 'code': False}
            if screenshots:
                for key, temp_path in screenshots.items():
                    if not temp_path or not os.path.exists(temp_path):
                        continue
                    dest_name = "screenshot.png" if key == 'preview' else f"{key}.png"
                    dest_path = component_dir / dest_name
                    shutil.move(temp_path, dest_path)
                    screenshot_summary[key] = True
            
            preview_path = component_dir / "screenshot.png"
            if not preview_path.exists():
                image_url = metadata.get("preview_image_url")
                if download_asset(image_url, preview_path):
                    screenshot_summary["preview"] = True
            
            # Save layout analysis if provided
            layout_summary = None
            if layout:
                layout_path = component_dir / "layout.json"
                with open(layout_path, 'w', encoding='utf-8') as f:
                    json.dump(layout, f, indent=2, ensure_ascii=False)
                layout_summary = {
                    'sections': len(layout.get('sections', [])),
                    'slots': len(layout.get('slots', [])),
                    'screenType': layout.get('screenType', 'page'),
                }
            
            # Add to index
            index_entry = {
                'name': component_name,
                'sanitized_name': sanitized_name,
                'url': metadata.get('url', ''),
                'description': metadata.get('description', ''),
                'category': metadata.get('category', ''),
                'tags': metadata.get('tags', []),
                'type': metadata.get('type', ''),
                'recommended_slots': metadata.get('recommended_slots', []),
                'source': metadata.get('source', self.source),
                'has_code': bool(code.get('code')),
                'screenshots': screenshot_summary,
            }
            if layout_summary:
                index_entry['layout'] = layout_summary
            self.components_index.append(index_entry)
            
            logger.info(f"Saved component: {sanitized_name}")
            return True
            
        except Exception as e:
            logger.error(f"Error saving component {component_name}: {str(e)}")
            return False
    
    def scrape_component(self, page: Page, component: dict) -> bool:
        """
        Scrape a single component.
        
        Args:
            page: Playwright page object
            component: Dictionary with 'name' and 'url' keys
            
        Returns:
            True if successful, False otherwise
        """
        try:
            component_name = component['name']
            component_url = component['url']
            
            logger.info(f"Scraping component: {component_name}")
            
            # Extract metadata
            metadata = self.adapter.metadata_extractor(page, component)
            metadata.setdefault('name', component_name)
            metadata.setdefault('url', component_url)
            metadata.setdefault('source', self.source)
            
            # Extract code
            code = self.adapter.code_extractor(page, component)
            metadata['client_only'] = metadata.get('client_only') or code.get('client_only', False)
            metadata['imports'] = code.get('imports', metadata.get('imports', []))
            metadata['dependencies'] = code.get('dependencies', metadata.get('dependencies', []))
            
            # Capture screenshots based on mode
            sanitized_name = self.sanitize_filename(component_name)
            screenshots = {}
            
            if self.screenshot_mode in {"preview", "both"}:
                temp_preview = self.components_dir / f"{sanitized_name}_preview.png"
                if capture_screenshot(
                    page,
                    str(temp_preview),
                    selectors=self.adapter.preview_selectors,
                ):
                    screenshots['preview'] = str(temp_preview)
            
            if self.screenshot_mode in {"code", "both"}:
                temp_code = self.components_dir / f"{sanitized_name}_code.png"
                code_selectors = list(self.adapter.code_selectors or CODE_PANEL_SELECTORS)
                if capture_screenshot(
                    page,
                    str(temp_code),
                    selectors=code_selectors,
                    allow_full_page_fallback=False,
                ):
                    screenshots['code'] = str(temp_code)
            
            # Perform layout analysis if enabled
            layout = None
            if self.layout_analysis:
                try:
                    # Use adapter's layout analyzer if available, otherwise use default
                    if self.adapter.layout_analyzer:
                        layout = self.adapter.layout_analyzer(page, sanitized_name, component_name)
                    else:
                        layout = analyze_layout(page, sanitized_name, component_name)
                    logger.info(f"Layout analysis complete for {component_name}")
                except Exception as e:
                    logger.warning(f"Layout analysis failed for {component_name}: {str(e)}")
            
            # Save component
            success = self.save_component(component_name, metadata, code, screenshots, layout)
            
            # Clean up temporary screenshots that weren't moved
            for temp_path in list(screenshots.values()):
                temp_file = Path(temp_path)
                if temp_file.exists():
                    destination = self.components_dir / sanitized_name
                    preview_target = destination / ("screenshot.png" if temp_file.name.endswith("_preview.png") else "code.png")
                    if not preview_target.exists():
                        temp_file.unlink()
            
            return success
            
        except Exception as e:
            logger.error(f"Error scraping component {component.get('name', 'unknown')}: {str(e)}")
            return False
    
    def generate_index(self):
        """Generate master index JSON file."""
        index_data = {
            'total_components': len(self.components_index),
            'components': self.components_index,
            'generated_at': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        
        with open(self.index_path, 'w', encoding='utf-8') as f:
            json.dump(index_data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Generated index with {len(self.components_index)} components")
    
    def run(self, max_components: int = None):
        """
        Run the scraper.
        
        Args:
            max_components: Maximum number of components to scrape (None for all)
        """
        logger.info("Starting component scraper...")
        
        with sync_playwright() as p:
            launch_kwargs = {
                "headless": True,
            }
            if self.browser_executable:
                launch_kwargs["executable_path"] = self.browser_executable
                logger.info(f"Using custom Chromium binary at {self.browser_executable}")

            browser = p.chromium.launch(**launch_kwargs)
            page = browser.new_page()
            
            try:
                # Find all components
                logger.info("Discovering components...")
                components = self.adapter.finder(page, max_components)
                
                if not components:
                    logger.warning("No components found!")
                    return
                
                logger.info(f"Found {len(components)} components")
                
                # Limit components if specified
                if max_components:
                    components = components[:max_components]
                    logger.info(f"Limiting to {max_components} components")
                
                # Scrape each component
                successful = 0
                failed = 0
                
                for i, component in enumerate(components, 1):
                    logger.info(f"Processing component {i}/{len(components)}: {component['name']}")
                    
                    if self.scrape_component(page, component):
                        successful += 1
                    else:
                        failed += 1
                    
                    # Rate limiting
                    if i < len(components):
                        logger.info(f"Waiting {self.delay} seconds before next request...")
                        time.sleep(self.delay)
                
                # Generate index
                self.generate_index()
                
                logger.info(f"Scraping complete! Successful: {successful}, Failed: {failed}")
                
            except Exception as e:
                logger.error(f"Fatal error during scraping: {str(e)}")
                raise
            finally:
                browser.close()


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Scrape Aceternity UI components')
    parser.add_argument('--output', '-o', default='library', help='Output directory')
    parser.add_argument('--max', '-m', type=int, help='Maximum number of components to scrape')
    parser.add_argument('--delay', '-d', type=float, default=2.0, help='Delay between requests (seconds)')
    parser.add_argument('--url', default='https://ui.aceternity.com', help='Base URL for Aceternity UI')
    parser.add_argument('--browser-path', help='Path to Chromium/Chrome executable')
    parser.add_argument(
        '--source',
        choices=['aceternity', 'aura', 'magic'],
        default='aceternity',
        help='Which source to scrape (default: aceternity)',
    )
    parser.add_argument(
        '--screenshots',
        choices=['preview', 'code', 'both'],
        default='both',
        help='Which screenshots to capture for each component',
    )
    parser.add_argument(
        '--layout-analysis',
        action='store_true',
        default=True,
        help='Perform layout analysis (default: True)',
    )
    parser.add_argument(
        '--no-layout-analysis',
        dest='layout_analysis',
        action='store_false',
        help='Disable layout analysis',
    )
    
    args = parser.parse_args()
    
    scraper = ComponentScraper(
        output_dir=args.output,
        base_url=args.url,
        delay=args.delay,
        browser_executable=args.browser_path,
        screenshot_mode=args.screenshots,
        source=args.source,
        layout_analysis=args.layout_analysis,
    )
    
    scraper.run(max_components=args.max)


if __name__ == '__main__':
    main()

